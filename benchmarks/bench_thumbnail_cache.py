"""
bench_thumbnail_cache.py — 縮圖快取路徑分裂驗證
==================================================
驗證目標（效能分析 P0-1：L2 快取路徑分裂 bug）：

  indexer.generate_l2_cache() 寫入   <project_root>/.cache/thumbnails/
  ui/widgets/image_delegate.py 讀取  <project_root>/ui/widgets/.cache/thumbnails/

  兩者路徑不同 → 索引器預產生的縮圖完全沒被 UI 使用，
  每張卡片首次顯示都退化成「全圖解碼」（慢 10 倍以上），
  且磁碟上存有兩份快取。

本腳本做兩件事：
  1. 量測「快取命中（256px WebP 載入）」vs「快取未命中（4000x3000 JPEG
     縮放解碼）」的單張耗時差距 → 證明修復快取路徑的效益。
  2. 檢查兩個快取目錄的實際狀態 → 修復後 ui/widgets/.cache 應不再成長
     （PASS 條件：ui/widgets/.cache 不存在或為空）。

用法：
    python bench_thumbnail_cache.py [--label baseline]
    python bench_thumbnail_cache.py --check-dirs   # 只檢查快取目錄狀態
"""

import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_common import (PROJECT_ROOT, print_speedup, print_table,
                          save_results, timeit)

ROOT_CACHE = os.path.join(PROJECT_ROOT, ".cache", "thumbnails")
UI_CACHE = os.path.join(PROJECT_ROOT, "ui", "widgets", ".cache", "thumbnails")

try:
    from PyQt6.QtCore import QSize, Qt
    from PyQt6.QtGui import QImage, QImageReader
    HAS_QT = True
except ImportError:
    HAS_QT = False

from PIL import Image, ImageDraw


def make_test_images(tmp_dir):
    """產生一張模擬照片的 4000x3000 JPEG 與其 256px WebP L2 快取。"""
    big_path = os.path.join(tmp_dir, "photo.jpg")
    l2_path = os.path.join(tmp_dir, "photo_l2.webp")

    img = Image.new("RGB", (4000, 3000))
    draw = ImageDraw.Draw(img)
    # 漸層 + 幾何圖形，模擬真實照片的壓縮特性（純色會讓解碼不真實地快）
    for y in range(0, 3000, 4):
        c = int(y / 3000 * 255)
        draw.line([(0, y), (4000, y)], fill=(c, 255 - c, (c * 3) % 255), width=4)
    for i in range(60):
        x, y = (i * 137) % 3800, (i * 211) % 2800
        draw.ellipse([x, y, x + 180, y + 180], fill=((i * 41) % 255, (i * 73) % 255, 200))
    img.save(big_path, "JPEG", quality=90)

    thumb = img.copy()
    thumb.thumbnail((256, 256), Image.Resampling.BICUBIC)
    thumb.save(l2_path, "WEBP", quality=80)
    return big_path, l2_path


def bench_qt(big_path, l2_path, target=(240, 180)):
    """以 UI 實際使用的 QImageReader 路徑量測。"""
    target_size = QSize(*target)

    def cache_miss():
        # ThumbnailLoader 階段二：全圖縮放解碼（快取未命中時的路徑）
        reader = QImageReader(big_path)
        orig = reader.size()
        reader.setAutoTransform(True)
        scaled = orig.scaled(target_size, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(scaled)
        img = reader.read()
        return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    def cache_hit():
        # ThumbnailLoader 階段一：載入 256px WebP 後平滑放大（快取命中路徑）
        image = QImage()
        image.load(l2_path)
        scaled = image.scaled(target_size, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        return scaled.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    return (timeit(cache_miss, repeat=10, warmup=2),
            timeit(cache_hit, repeat=10, warmup=2))


def bench_pil(big_path, l2_path, target=(240, 180)):
    """PyQt6 不可用時的 PIL 後備量測（趨勢相同）。"""

    def cache_miss():
        with Image.open(big_path) as img:
            img.thumbnail(target, Image.Resampling.BICUBIC)
            return img.convert("RGBA")

    def cache_hit():
        with Image.open(l2_path) as img:
            img = img.resize(target, Image.Resampling.BICUBIC)
            return img.convert("RGBA")

    return (timeit(cache_miss, repeat=10, warmup=2),
            timeit(cache_hit, repeat=10, warmup=2))


def count_dir(path):
    if not os.path.isdir(path):
        return None
    n = 0
    with os.scandir(path) as it:
        for entry in it:
            if entry.is_file():
                n += 1
    return n


def check_cache_dirs():
    """檢查快取目錄分裂狀態。修復並遷移後，UI 端目錄應不存在或為空。"""
    print("\n=== 快取目錄狀態檢查 ===")
    root_n = count_dir(ROOT_CACHE)
    ui_n = count_dir(UI_CACHE)
    print(f"  indexer 寫入端  {ROOT_CACHE}")
    print(f"      檔案數: {root_n if root_n is not None else '（目錄不存在）'}")
    print(f"  UI 讀取端       {UI_CACHE}")
    print(f"      檔案數: {ui_n if ui_n is not None else '（目錄不存在）'}")
    split = bool(ui_n)  # UI 端目錄有檔案 = 路徑仍分裂（或尚未清理遷移）
    print(f"  結論: {'FAIL — 快取路徑仍分裂（UI 端目錄非空）' if split else 'PASS — 快取路徑已統一'}")
    return {"root_cache_files": root_n, "ui_cache_files": ui_n, "split": split}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--check-dirs", action="store_true", help="只檢查快取目錄狀態")
    args = parser.parse_args()

    if args.check_dirs:
        check_cache_dirs()
        return

    with tempfile.TemporaryDirectory(prefix="esm_bench_thumb_") as tmp:
        print("產生 4000x3000 測試 JPEG 與 256px WebP L2 快取...")
        big_path, l2_path = make_test_images(tmp)
        size_mb = os.path.getsize(big_path) / 1048576
        print(f"  JPEG: {size_mb:.1f} MB")

        if HAS_QT:
            print("使用 QImageReader（與 UI 相同的解碼路徑）量測...")
            miss, hit = bench_qt(big_path, l2_path)
            backend = "qt"
        else:
            print("[警告] PyQt6 不可用，改用 PIL 後備量測。")
            miss, hit = bench_pil(big_path, l2_path)
            backend = "pil"

    print_table("單張縮圖載入耗時", [
        ("快取未命中（全圖縮放解碼）＝現況首次顯示", miss),
        ("快取命中（256px WebP）＝修復路徑後", hit),
    ])
    print_speedup("快取命中 vs 未命中", miss, hit)

    dir_status = check_cache_dirs()
    save_results("thumbnail_cache", args.label, {
        "cache_miss_full_decode": miss,
        "cache_hit_l2_webp": hit,
    }, extra={"backend": backend, "dir_status": dir_status})


if __name__ == "__main__":
    main()
