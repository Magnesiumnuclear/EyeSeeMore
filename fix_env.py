"""
fix_env.py  –  User_Environment (Portable Python 3.10) 修復腳本
================================================================
修正事項：
  1. 安裝缺失的 faiss-cpu
  2. 將 opencv-python（完整版）替換為 opencv-python-headless
  3. 將 numpy 降版至 <2.0，避免 API 不相容
  4. 確認 python310._pth 中 `import site` 未被註釋

用法：
    python fix_env.py          # 互動模式，逐步確認
    python fix_env.py --yes    # 全自動模式，跳過所有確認
"""

import subprocess
import sys
import os
import argparse
from pathlib import Path

# ── 常數 ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent.resolve()
ENV_DIR      = SCRIPT_DIR / "User_Environment"
PYTHON_EXE   = ENV_DIR / "python.exe"
PTH_FILE     = ENV_DIR / "python310._pth"

# (套件名稱, pip 安裝規格, 檢查用的 import 名稱)
REQUIRED_PACKAGES: list[tuple[str, str, str]] = [
    ("faiss-cpu",                  "faiss-cpu>=1.7.4",              "faiss"),
    ("opencv-python-headless",     "opencv-python-headless>=4.8.0", "cv2"),
    ("numpy",                      "numpy>=1.24.0,<2.0",            "numpy"),
    ("PyQt6",                      "PyQt6==6.10.2",                 "PyQt6"),
    ("onnxruntime-directml",       "onnxruntime-directml==1.23.0",  "onnxruntime"),
    ("Pillow",                     "Pillow>=10.0.0",                "PIL"),
    ("transformers",               "transformers>=4.35.0",          "transformers"),
    ("pyclipper",                  "pyclipper>=1.3.0",              "pyclipper"),
    ("shapely",                    "shapely>=2.0.0",                "shapely"),
    ("psutil",                     "psutil>=5.9.0",                 "psutil"),
]

# 安裝前必須先移除的衝突套件（移除目標, 原因）
CONFLICTING_PACKAGES: list[tuple[str, str]] = [
    ("opencv-python",
     "完整版帶獨立 Qt DLL，會與 PyQt6 衝突"),
    ("onnxruntime",
     "與 onnxruntime-directml 不可並存"),
]

# ── 工具 ─────────────────────────────────────────────────────────────────────

def _run_pip(*args: str) -> bool:
    """使用 User_Environment 的 python.exe 執行 pip 指令，回傳是否成功。"""
    cmd = [str(PYTHON_EXE), "-m", "pip", *args]
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, text=True, encoding="utf-8")
    return result.returncode == 0


def _pkg_version(import_name: str) -> str | None:
    """在 User_Environment 中取得套件版本字串，失敗時回傳 None。"""
    code = (
        f"import importlib.metadata as m, sys;"
        f"print(m.version('{import_name}'))"
    )
    try:
        r = subprocess.run(
            [str(PYTHON_EXE), "-c", code],
            capture_output=True, text=True, encoding="utf-8", timeout=15
        )
        ver = r.stdout.strip()
        return ver if ver else None
    except Exception:
        return None


def _ask(prompt: str, auto_yes: bool) -> bool:
    if auto_yes:
        print(f"  [自動確認] {prompt} → 是")
        return True
    ans = input(f"  {prompt} [Y/n] ").strip().lower()
    return ans in ("", "y", "yes")


# ── 步驟 1：檢查 .pth 檔案 ───────────────────────────────────────────────────

def check_pth(auto_yes: bool) -> None:
    print("\n[1/3] 檢查 python310._pth ...")
    if not PTH_FILE.exists():
        print(f"  [錯誤] 找不到 {PTH_FILE}，請確認 User_Environment 資料夾完整。")
        return

    lines   = PTH_FILE.read_text(encoding="utf-8").splitlines()
    changed = False
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        # 被註解掉的 import site
        if stripped.startswith("#") and "import site" in stripped:
            if _ask("發現 `import site` 被註解，是否解除注釋？", auto_yes):
                new_lines.append("import site")
                changed = True
                print("  ✔  已解除 `import site` 的注釋")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # 完全不存在 import site
    has_import_site = any(
        l.strip() == "import site" for l in new_lines
    )
    if not has_import_site:
        if _ask("`import site` 不存在，是否自動加入？", auto_yes):
            new_lines.append("import site")
            changed = True
            print("  ✔  已加入 `import site`")

    if changed:
        PTH_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"  ✔  {PTH_FILE.name} 已更新")
    else:
        print("  ✔  python310._pth 設定正常，無需修改")


# ── 步驟 2：移除衝突套件 ─────────────────────────────────────────────────────

def remove_conflicts(auto_yes: bool) -> None:
    print("\n[2/3] 檢查並移除衝突套件 ...")
    for pkg, reason in CONFLICTING_PACKAGES:
        ver = _pkg_version(pkg)
        if ver is None:
            print(f"  ✔  {pkg} 未安裝，無衝突")
            continue
        print(f"  ⚠  發現衝突套件：{pkg} {ver}（{reason}）")
        if _ask(f"是否移除 {pkg}？", auto_yes):
            ok = _run_pip("uninstall", pkg, "-y")
            print(f"  {'✔' if ok else '✘'}  {pkg} {'移除成功' if ok else '移除失敗'}")


# ── 步驟 3：安裝 / 修復必要套件 ──────────────────────────────────────────────

def install_packages(auto_yes: bool) -> None:
    print("\n[3/3] 檢查並安裝必要套件 ...")
    for display_name, spec, import_name in REQUIRED_PACKAGES:
        ver = _pkg_version(import_name if import_name != "cv2" else "opencv-python-headless")
        # faiss 的 metadata 名稱跟 import 不同，用 pip show 補查
        if import_name == "faiss":
            r = subprocess.run(
                [str(PYTHON_EXE), "-m", "pip", "show", "faiss-cpu"],
                capture_output=True, text=True, encoding="utf-8"
            )
            ver = "已安裝" if r.returncode == 0 and r.stdout.strip() else None

        if ver:
            print(f"  ✔  {display_name} 已安裝（{ver}）")
            # numpy 特別處理：>=2.0 需要強制降版
            if display_name == "numpy" and ver.startswith("2."):
                print(f"     ⚠  numpy {ver} >= 2.0，需降版")
                if _ask(f"是否強制安裝 {spec}？", auto_yes):
                    _run_pip("install", spec, "--force-reinstall")
        else:
            print(f"  ✘  {display_name} 未安裝")
            if _ask(f"是否安裝 {spec}？", auto_yes):
                ok = _run_pip("install", spec)
                print(f"  {'✔' if ok else '✘'}  {display_name} {'安裝成功' if ok else '安裝失敗'}")


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="修復 User_Environment Portable Python")
    ap.add_argument("--yes", "-y", action="store_true", help="全自動模式，跳過所有確認")
    args = ap.parse_args()
    auto = args.yes

    print("=" * 60)
    print("  EyeSeeMore – User_Environment 修復工具")
    print("=" * 60)

    if not PYTHON_EXE.exists():
        print(f"\n[錯誤] 找不到 {PYTHON_EXE}")
        print("  請確認 User_Environment 資料夾存在且包含 python.exe")
        return 1

    print(f"  目標 Python：{PYTHON_EXE}")

    check_pth(auto)
    remove_conflicts(auto)
    install_packages(auto)

    print("\n" + "=" * 60)
    print("  修復完成！請重新執行 build_installer.bat 進行打包。")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
