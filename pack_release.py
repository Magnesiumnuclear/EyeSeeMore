"""
pack_release.py  –  EyeSeeMore 發佈套件打包腳本
=======================================================
由 build_installer.bat 呼叫；亦可獨立執行：

    python pack_release.py [<project_root>] [<build_dir>]

    project_root  預設為此檔案所在目錄（專案根目錄）
    build_dir     預設為 <project_root>/build

輸出目錄：EyeSeeMore_installer/
    ├── EyeSeeMore_Setup.exe   ← 安裝程式（複製自 build/）
    ├── App_Code.zip           ← Python 原始碼 + Launcher.exe
    ├── Runtime.zip            ← Python embeddable 環境
    └── AI_Models.zip          ← ONNX 模型（資料夾存在時才打包）
"""

import sys
import os
import shutil
import zipfile
import time
from pathlib import Path

# ── 常數 ─────────────────────────────────────────────────────────────────────

# App_Code.zip 要包含的項目（相對於 project_root）
APP_CODE_ENTRIES = [
    "Blur-main.py",
    "indexer.py",
    "onnx_ocr.py",
    "export_clip_onnx.py",

    "core",
    "ui",
    "utils",
    "themes",
    "languages",
]

# 打包時一律排除的目錄名稱
EXCLUDE_DIRS = {
    "__pycache__", ".git", ".venv", ".venv-onnx",
    ".vscode", ".cache", "EyeSeeMore_installer", "build",
}

# 打包時一律排除的副檔名
EXCLUDE_EXTS = {".pyc", ".pyo"}


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def _fmt_size(path: Path) -> str:
    """回傳人類可讀的檔案大小字串（自動選 KB / MB）。"""
    size = path.stat().st_size
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{size / 1024:.0f} KB"


# 進度條寬度（# 字元個數）
_BAR_W = 20
# 每寫入多少個檔案才刷新一次畫面（避免過度刷新拖慢速度）
_FLUSH_EVERY = 30


def _collect_dir(src: Path,
                 exclude_dirs: set | None = None,
                 exclude_exts: set | None = None,
                 arc_root: Path | None = None) -> list[tuple[Path, str]]:
    """
    遞迴收集 src 目錄下所有合格檔案。
    回傳 (絕對路徑, 壓縮包內路徑) 清單。
    arc_root：計算相對路徑的基準目錄，預設為 src 本身。
    """
    if exclude_dirs is None:
        exclude_dirs = set()
    if exclude_exts is None:
        exclude_exts = set()
    if arc_root is None:
        arc_root = src

    result: list[tuple[Path, str]] = []
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in exclude_dirs)
        for fname in sorted(files):
            if Path(fname).suffix.lower() in exclude_exts:
                continue
            abs_path = Path(root) / fname
            result.append((abs_path, str(abs_path.relative_to(arc_root))))
    return result


def _zip_with_progress(label: str,
                       file_pairs: list[tuple[Path, str]],
                       out_zip: Path,
                       compress_type: int = zipfile.ZIP_DEFLATED,
                       compresslevel: int | None = 6) -> int:
    """
    逐一壓縮 file_pairs，並以 \\r 動態更新進度條（以位元組計算進度）。
    compress_type: zipfile.ZIP_DEFLATED（壓縮）或 zipfile.ZIP_STORED（僅儲存）
    回傳：寫入的檔案總數。
    """
    total_bytes = sum(p.stat().st_size for p, _ in file_pairs)
    done_bytes  = 0
    total_n     = len(file_pairs)
    t0          = time.time()

    def _draw(done_b: int, i: int) -> None:
        pct      = done_b * 100 / total_bytes if total_bytes else 100.0
        filled   = int(_BAR_W * pct / 100)
        bar      = "#" * filled + "-" * (_BAR_W - filled)
        done_mb  = done_b  / 1024 / 1024
        total_mb = total_bytes / 1024 / 1024
        sys.stdout.write(
            f"\r  [{bar}] {pct:5.1f}%  "
            f"{done_mb:7.1f} / {total_mb:.1f} MB  "
            f"({i}/{total_n})  {label}"
            "   "           # 額外空白覆蓋可能的上一行殘留
        )
        sys.stdout.flush()

    # ZIP_STORED 模式無需 compresslevel
    open_kwargs: dict = {"compression": compress_type}
    if compress_type == zipfile.ZIP_DEFLATED and compresslevel is not None:
        open_kwargs["compresslevel"] = compresslevel

    with zipfile.ZipFile(out_zip, "w", **open_kwargs) as zf:
        for i, (abs_path, arc_name) in enumerate(file_pairs, 1):
            done_bytes += abs_path.stat().st_size
            zf.write(abs_path, arc_name)
            if i % _FLUSH_EVERY == 0 or i == total_n:
                _draw(done_bytes, i)

    elapsed  = time.time() - t0
    size_mb  = out_zip.stat().st_size / 1024 / 1024
    mode_str = "(僅儲存)" if compress_type == zipfile.ZIP_STORED else "(壓縮後)"
    sys.stdout.write(
        f"\r  [{'#' * _BAR_W}] 100.0%  "
        f"{size_mb:.1f} MB {mode_str}  "
        f"({total_n} 個檔案, {elapsed:.1f}s)  {label}  ✔\n"
    )
    sys.stdout.flush()
    return total_n


# ── 打包步驟 ──────────────────────────────────────────────────────────────────

def pack_runtime(project_root: Path, out_dir: Path) -> bool:
    src = project_root / "User_Environment"
    if not src.exists():
        print("  [警告] 找不到 User_Environment\\，跳過 Runtime.zip")
        return True

    out_zip = out_dir / "Runtime.zip"
    pairs   = _collect_dir(src)
    total_mb = sum(p.stat().st_size for p, _ in pairs) / 1024 / 1024
    print(f"  準備打包 Runtime.zip（{len(pairs)} 個檔案，{total_mb:.1f} MB）...")
    _zip_with_progress("Runtime.zip", pairs, out_zip)
    return True


def pack_models(project_root: Path, out_dir: Path) -> bool:
    src = project_root / "models"
    if not src.exists():
        print("  [警告] 找不到 models\\，跳過 AI_Models.zip")
        return True

    out_zip  = out_dir / "AI_Models.zip"
    pairs    = _collect_dir(src, arc_root=project_root)
    total_mb = sum(p.stat().st_size for p, _ in pairs) / 1024 / 1024
    print(f"  準備打包 AI_Models.zip（{len(pairs)} 個檔案，{total_mb:.1f} MB）...")
    print("  [模式] ZIP_STORED（模型檔已壓縮，跳過再壓縮以加速打包）")
    _zip_with_progress("AI_Models.zip", pairs, out_zip,
                       compress_type=zipfile.ZIP_STORED)
    return True


def pack_app_code(project_root: Path, out_dir: Path, build_dir: Path) -> bool:
    out_zip = out_dir / "App_Code.zip"
    pairs: list[tuple[Path, str]] = []

    # ── 收集清單中的所有項目 ────────────────────────────────────────────────
    for entry in APP_CODE_ENTRIES:
        src = project_root / entry
        if not src.exists():
            if entry == "config.json":
                print(f"  [略過] {entry} 不存在（安裝後首次啟動會自動建立）")
                continue
            print(f"  [警告] {entry} 不存在，略過")
            continue

        if src.is_file():
            pairs.append((src, entry))
        else:
            # 資料夾：arc_name 保留相對於 project_root 的路徑結構
            for abs_path, _ in _collect_dir(src,
                                            exclude_dirs=EXCLUDE_DIRS,
                                            exclude_exts=EXCLUDE_EXTS,
                                            arc_root=project_root):
                pairs.append((abs_path, str(abs_path.relative_to(project_root))))

    # ── 加入編譯好的 Launcher ───────────────────────────────────────────────
    launcher = build_dir / "EyeSeeMore_Launcher.exe"
    if not launcher.exists():
        print(f"\n  [錯誤] 找不到 {launcher}")
        print("  請先完成 C++ 編譯後再執行打包步驟。")
        return False
    pairs.append((launcher, "EyeSeeMore_Launcher.exe"))

    print(f"  準備打包 App_Code.zip（{len(pairs)} 個檔案）...")
    _zip_with_progress("App_Code.zip", pairs, out_zip)
    return True


def copy_setup_exe(build_dir: Path, out_dir: Path) -> bool:
    src = build_dir / "EyeSeeMore_Setup.exe"
    if not src.exists():
        print(f"  [錯誤] 找不到 {src}")
        return False
    dst = out_dir / "EyeSeeMore_Setup.exe"
    shutil.copy2(src, dst)
    print(f"  ✔  EyeSeeMore_Setup.exe  {_fmt_size(dst)}")
    return True


# ── 主流程 ────────────────────────────────────────────────────────────────────

def _print_summary(out_dir: Path) -> None:
    print("=" * 55)
    print("  發佈套件已打包完成！")
    print(f"  位置：{out_dir}")
    print("=" * 55)
    print()
    print(f"  {'檔案名稱':<32} {'大小':>10}")
    print(f"  {'-'*32} {'-'*10}")
    for f in sorted(out_dir.iterdir()):
        size = f.stat().st_size / 1024 / 1024
        print(f"  {f.name:<32} {size:>9.1f} MB")
    print()


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("project_root", nargs="?", default=None)
    ap.add_argument("build_dir",    nargs="?", default=None)
    ap.add_argument("--task", default="all",
                    choices=["all", "setup", "appcode", "runtime", "models"])
    args = ap.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root \
                   else Path(__file__).parent.resolve()
    build_dir    = Path(args.build_dir).resolve() if args.build_dir \
                   else project_root / "build"
    out_dir      = project_root / "EyeSeeMore_installer"

    print(f"  專案根目錄：{project_root}")
    print(f"  Build 目錄：{build_dir}")
    print(f"  輸出目錄  ：{out_dir}")
    print()

    task = args.task

    # ── 建立或重用輸出目錄 ────────────────────────────────────────────────
    if task in ("all", "setup"):
        # 全量或初始化任務：先清空舊內容
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir()
    else:
        out_dir.mkdir(exist_ok=True)

    # ── 依任務執行 ────────────────────────────────────────────────────────

    if task == "setup":
        print("── Setup.exe 複製 ──")
        if not copy_setup_exe(build_dir, out_dir):
            return 1

    elif task == "appcode":
        print("── App_Code.zip ──")
        if not pack_app_code(project_root, out_dir, build_dir):
            return 1

    elif task == "runtime":
        print("── Runtime.zip ──")
        if not pack_runtime(project_root, out_dir):
            return 1

    elif task == "models":
        print("── AI_Models.zip ──")
        if not pack_models(project_root, out_dir):
            return 1
        _print_summary(out_dir)

    else:  # "all" — 舊有行為：一次完成所有步驟
        steps = [
            ("Runtime.zip",    lambda: pack_runtime(project_root, out_dir)),
            ("AI_Models.zip",  lambda: pack_models(project_root, out_dir)),
            ("App_Code.zip",   lambda: pack_app_code(project_root, out_dir, build_dir)),
            ("Setup.exe 複製", lambda: copy_setup_exe(build_dir, out_dir)),
        ]
        for label, fn in steps:
            print(f"── {label} ──")
            ok = fn()
            print()
            if not ok:
                print(f"[!] 打包流程在「{label}」步驟中止。")
                return 1
        _print_summary(out_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
