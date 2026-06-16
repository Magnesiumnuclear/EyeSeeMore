"""
bench_vectorize.py — CLIP 向量建立效能量測
============================================
量測 indexer.py「建立向量數據」路徑的關鍵成本,作為優化前後的對照基準。
**只量測,不修改 indexer。** 沿用 bench_common,結果 JSON 自動綁定 git commit。

量測項目(對應 PERFORMANCE_NOTES / indexer 分析):
  1. 模型輸入 shape → 判斷是否「動態 batch 軸」(調大 batch 的前提)。
  2. 各 batch size 的純 ONNX session.run 吞吐(張/秒、每張 ms)。
     —— 反映 batch 太小造成的 GPU 低載;曲線在哪裡飽和就是 batch 的甜蜜點。
  3. NumpyPreprocess 前處理單張成本。
  4. 解碼+前處理(CPU 階段)單張成本 vs 純推論每張成本
     —— 兩者的差距即「CPU/GPU 管線化(pipelining)」能省下的上限。

需要真實的 {model}_image.onnx;找不到時推論段 skip(前處理段仍可量)。

用法:
    python bench_vectorize.py [--label baseline]
    python bench_vectorize.py --batches 4,8,16,32,64 --repeat 8
    python bench_vectorize.py --model-path <path-to-image.onnx>
    python bench_vectorize.py --inspect      # 只印模型輸入 shape / providers
"""

import argparse
import glob
import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_common import (PROJECT_ROOT, fmt_seconds, print_table,
                          save_results, timeit)

# 量測前處理需 import indexer(NumpyPreprocess);專案根必須在 sys.path 上
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import onnxruntime as ort
    HAS_ORT = True
except Exception:
    HAS_ORT = False

DEFAULT_MODEL = "xlm-roberta-large-ViT-H-14"
IMG_SIZE = 224


# ──────────────────────────────────────────────────────────
#  模型解析 / 載入
# ──────────────────────────────────────────────────────────
def read_model_name():
    """唯讀讀取 config.json 的 model_name(不經 ConfigManager,避免回寫副作用)。"""
    try:
        with open(os.path.join(PROJECT_ROOT, "config.json"), encoding="utf-8") as f:
            return json.load(f).get("model_name") or DEFAULT_MODEL
    except Exception:
        return DEFAULT_MODEL


def resolve_model_path(model_name, override=None):
    if override:
        return override
    onnx_dir = os.path.join(PROJECT_ROOT, "models", "onnx_clip")
    p = os.path.join(onnx_dir, f"{model_name}_image.onnx")
    if os.path.exists(p):
        return p
    cands = sorted(glob.glob(os.path.join(onnx_dir, "*_image.onnx")))
    return cands[0] if cands else p


def make_session(path):
    """與 indexer.load_ai_models 相同的建立方式(無 SessionOptions),確保 baseline 忠實。"""
    providers = (['DmlExecutionProvider', 'CPUExecutionProvider']
                 if 'DmlExecutionProvider' in ort.get_available_providers()
                 else ['CPUExecutionProvider'])
    sess = ort.InferenceSession(path, providers=providers)
    return sess, providers


def describe_input(sess):
    inp = sess.get_inputs()[0]
    shape = list(inp.shape)
    batch_dim = shape[0] if shape else None
    # 動態:batch 維是字串(symbolic)或 -1 / None;靜態:是具體整數
    dynamic = not isinstance(batch_dim, int)
    return inp.name, shape, dynamic


# ──────────────────────────────────────────────────────────
#  量測
# ──────────────────────────────────────────────────────────
def bench_inference(sess, input_name, batch, repeat, warmup):
    x = np.random.rand(batch, 3, IMG_SIZE, IMG_SIZE).astype(np.float32)

    def run():
        sess.run(None, {input_name: x})

    return timeit(run, repeat=repeat, warmup=warmup)


def bench_preprocess(repeat, warmup):
    """NumpyPreprocess 單張成本(輸入為已解碼的 PIL 影像)。"""
    from PIL import Image, ImageDraw
    from indexer import NumpyPreprocess
    pp = NumpyPreprocess(IMG_SIZE)
    img = Image.new("RGB", (4000, 3000))
    d = ImageDraw.Draw(img)
    for y in range(0, 3000, 6):
        d.line([(0, y), (4000, y)], fill=(y % 256, (y * 2) % 256, 90), width=6)

    return timeit(lambda: pp(img), repeat=repeat, warmup=warmup)


def bench_decode_preprocess(repeat, warmup):
    """解碼(Image.open)+ EXIF 轉正 + RGB 安全轉換 + NumpyPreprocess 的單張 CPU 階段。"""
    from PIL import Image, ImageDraw, ImageOps
    from indexer import NumpyPreprocess, pil_to_rgb_safe
    pp = NumpyPreprocess(IMG_SIZE)
    with tempfile.TemporaryDirectory(prefix="esm_bench_vec_") as tmp:
        jpg = os.path.join(tmp, "p.jpg")
        img = Image.new("RGB", (4000, 3000))
        d = ImageDraw.Draw(img)
        for i in range(80):
            x, y = (i * 137) % 3800, (i * 211) % 2800
            d.ellipse([x, y, x + 200, y + 200], fill=((i * 41) % 256, (i * 73) % 256, 200))
        img.save(jpg, "JPEG", quality=90)

        def decode_prep():
            with Image.open(jpg) as im:
                t = ImageOps.exif_transpose(im)
                rgb = pil_to_rgb_safe(t)
            pp(rgb)

        return timeit(decode_prep, repeat=repeat, warmup=warmup)


# ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--batches", default="4,8,16,32",
                        help="逗號分隔的 batch 大小(預設 4,8,16,32)")
    parser.add_argument("--repeat", type=int, default=8, help="每個 batch 計時次數")
    parser.add_argument("--warmup", type=int, default=2, help="計時前的暖機次數(DML 需要)")
    parser.add_argument("--model-path", default=None, help="直接指定 image encoder .onnx 路徑")
    parser.add_argument("--inspect", action="store_true", help="只印模型輸入 shape / providers")
    args = parser.parse_args()

    if not HAS_ORT:
        print("[錯誤] onnxruntime 不可用,無法量測。")
        sys.exit(1)

    model_name = read_model_name()
    model_path = resolve_model_path(model_name, args.model_path)
    metrics = {}
    extra = {"model_name": model_name, "model_path": model_path}

    print(f"模型: {model_name}")
    print(f"路徑: {model_path}")

    sess = None
    input_name = None
    if os.path.exists(model_path):
        print("載入 ONNX session(含外部權重,可能需數秒)...")
        sess, providers = make_session(model_path)
        input_name, in_shape, dynamic = describe_input(sess)
        extra.update({"providers": providers, "input_name": input_name,
                      "input_shape": [str(s) for s in in_shape],
                      "dynamic_batch": dynamic})
        print(f"\n=== 模型輸入 ===")
        print(f"  Providers : {providers}")
        print(f"  Input     : {input_name}  shape={in_shape}")
        print(f"  動態 batch 軸: {'是 → 可自由調大 batch' if dynamic else '否(固定!調大 batch 需重匯出帶 dynamic axes 的模型)'}")
    else:
        print(f"[警告] 找不到模型檔,跳過推論量測(僅量前處理)。")
        extra["inference_skipped"] = "model not found"

    if args.inspect:
        save_results("vectorize", args.label, metrics, extra=extra)
        return

    # ── 1. 各 batch 推論吞吐 ──
    if sess is not None:
        batches = [int(b) for b in args.batches.split(",") if b.strip()]
        throughputs = {}
        per_image_ms = {}
        rows = []
        for b in batches:
            try:
                stats = bench_inference(sess, input_name, b, args.repeat, args.warmup)
            except Exception as e:
                msg = str(e).splitlines()[0][:80]
                print(f"  batch {b:>3}: 失敗(可能 batch 軸固定)— {msg}")
                throughputs[b] = None
                continue
            metrics[f"infer_batch{b}_per_run"] = stats
            ips = b / stats["median"] if stats["median"] > 0 else 0
            throughputs[b] = round(ips, 1)
            per_image_ms[b] = round(stats["median"] / b * 1000, 2)
            rows.append((f"batch {b:>3}  ({throughputs[b]:>7.1f} 張/秒, {per_image_ms[b]:>6.2f} ms/張)", stats))
        extra["throughput_img_per_s"] = throughputs
        extra["per_image_ms"] = per_image_ms
        print_table("ONNX 推論:每次 session.run 耗時(batch 越大每張應越省,直到飽和)", rows)

    # ── 2. 前處理 / 解碼成本 ──
    print("\n量測前處理(NumpyPreprocess)與 解碼+前處理 單張成本...")
    pp_stats = bench_preprocess(max(args.repeat, 10), args.warmup)
    dp_stats = bench_decode_preprocess(max(args.repeat, 10), args.warmup)
    metrics["preprocess_per_image"] = pp_stats
    metrics["decode_preprocess_per_image"] = dp_stats
    print_table("CPU 前處理單張成本", [
        ("preprocess(NumpyPreprocess)", pp_stats),
        ("decode + 轉正 + RGB + preprocess(完整 CPU 階段)", dp_stats),
    ])

    # ── 3. 管線化潛力提示 ──
    if sess is not None and per_image_ms:
        # 取一個中等 batch 的每張推論時間,與 CPU 階段每張時間對比
        ref_b = max((b for b in per_image_ms), default=None)
        if ref_b:
            gpu_ms = per_image_ms[ref_b]
            cpu_ms = dp_stats["median"] * 1000
            overlap = min(gpu_ms, cpu_ms)
            print(f"\n=== CPU/GPU 管線化潛力(以 batch {ref_b} 為例) ===")
            print(f"  CPU 每張(解碼+前處理): {cpu_ms:6.2f} ms")
            print(f"  GPU 每張(推論)       : {gpu_ms:6.2f} ms")
            print(f"  目前為序列執行 → 每張約 {cpu_ms + gpu_ms:6.2f} ms")
            print(f"  管線化後上限約       : {max(gpu_ms, cpu_ms):6.2f} ms/張(可省下 ~{overlap:.2f} ms/張)")
            extra["pipeline_ref_batch"] = ref_b
            extra["cpu_stage_ms"] = round(cpu_ms, 2)

    save_results("vectorize", args.label, metrics, extra=extra)


if __name__ == "__main__":
    main()
