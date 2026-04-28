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
    "config.json",
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


def zip_directory(src: Path, out_zip: Path,
                  arc_prefix: str = "",
                  exclude_dirs: set | None = None,
                  exclude_exts: set | None = None) -> int:
    """
    將 src 資料夾完整壓縮成 out_zip。

    arc_prefix  ── 壓縮包內的路徑前綴（空字串表示放在根目錄）
    回傳：加入的檔案數目
    """
    if exclude_dirs is None:
        exclude_dirs = set()
    if exclude_exts is None:
        exclude_exts = set()

    count = 0
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(src):
            dirs[:] = sorted(d for d in dirs if d not in exclude_dirs)
            for fname in sorted(files):
                if Path(fname).suffix.lower() in exclude_exts:
                    continue
                abs_path = Path(root) / fname
                rel      = abs_path.relative_to(src)
                arc_name = str(Path(arc_prefix) / rel) if arc_prefix else str(rel)
                zf.write(abs_path, arc_name)
                count += 1
    return count


# ── 打包步驟 ──────────────────────────────────────────────────────────────────

def pack_runtime(project_root: Path, out_dir: Path) -> bool:
    src = project_root / "User_Environment"
    if not src.exists():
        print("  [警告] 找不到 User_Environment\\，跳過 Runtime.zip")
        return True  # 非致命

    out_zip = out_dir / "Runtime.zip"
    print("  正在打包 Runtime.zip ...")
    t0 = time.time()
    n  = zip_directory(src, out_zip)
    print(f"  ✔  Runtime.zip  {_fmt_size(out_zip)}  ({n} 個檔案, {time.time()-t0:.1f}s)")
    return True


def pack_models(project_root: Path, out_dir: Path) -> bool:
    src = project_root / "models"
    if not src.exists():
        print("  [警告] 找不到 models\\，跳過 AI_Models.zip")
        return True  # 非致命

    out_zip = out_dir / "AI_Models.zip"
    print("  正在打包 AI_Models.zip（模型檔較大，請稍候）...")
    t0 = time.time()
    n  = zip_directory(src, out_zip)
    print(f"  ✔  AI_Models.zip  {_fmt_size(out_zip)}  ({n} 個檔案, {time.time()-t0:.1f}s)")
    return True


def pack_app_code(project_root: Path, out_dir: Path, build_dir: Path) -> bool:
    out_zip = out_dir / "App_Code.zip"
    print("  正在打包 App_Code.zip ...")
    t0    = time.time()
    count = 0

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:

        # ── 逐一處理清單中的項目 ───────────────────────────────────────────
        for entry in APP_CODE_ENTRIES:
            src = project_root / entry
            if not src.exists():
                # config.json 允許不存在（使用者可能尚未設定）
                if entry == "config.json":
                    print(f"    [略過] {entry} 不存在（安裝後首次啟動會自動建立）")
                    continue
                print(f"    [警告] {entry} 不存在，略過")
                continue

            if src.is_file():
                zf.write(src, entry)
                count += 1
            else:
                # 資料夾：遞迴加入，保留相對路徑結構，並套用排除規則
                for root, dirs, files in os.walk(src):
                    dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
                    for fname in sorted(files):
                        if Path(fname).suffix.lower() in EXCLUDE_EXTS:
                            continue
                        abs_path = Path(root) / fname
                        arc_name = str(abs_path.relative_to(project_root))
                        zf.write(abs_path, arc_name)
                        count += 1

        # ── 加入編譯好的 Launcher ────────────────────────────────────────
        launcher = build_dir / "EyeSeeMore_Launcher.exe"
        if not launcher.exists():
            print(f"\n  [錯誤] 找不到 {launcher}")
            print("  請先完成 C++ 編譯後再執行打包步驟。")
            return False
        zf.write(launcher, "EyeSeeMore_Launcher.exe")
        count += 1
        print(f"    ✔  EyeSeeMore_Launcher.exe 已加入")

    print(f"  ✔  App_Code.zip  {_fmt_size(out_zip)}  ({count} 個檔案, {time.time()-t0:.1f}s)")
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

def main() -> int:
    # 解析引數
    project_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 \
                   else Path(__file__).parent.resolve()
    build_dir    = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 \
                   else project_root / "build"
    out_dir      = project_root / "EyeSeeMore_installer"

    print(f"  專案根目錄：{project_root}")
    print(f"  Build 目錄：{build_dir}")
    print(f"  輸出目錄  ：{out_dir}")
    print()

    # ── 準備輸出目錄（先清空舊內容）────────────────────────────────────────
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir()

    # ── 依序打包 ──────────────────────────────────────────────────────────

    steps = [
        ("Runtime.zip",      lambda: pack_runtime(project_root, out_dir)),
        ("AI_Models.zip",    lambda: pack_models(project_root, out_dir)),
        ("App_Code.zip",     lambda: pack_app_code(project_root, out_dir, build_dir)),
        ("Setup.exe 複製",   lambda: copy_setup_exe(build_dir, out_dir)),
    ]

    for label, fn in steps:
        print(f"── {label} ──")
        ok = fn()
        print()
        if not ok:
            print(f"[!] 打包流程在「{label}」步驟中止。")
            return 1

    # ── 摘要 ─────────────────────────────────────────────────────────────
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
