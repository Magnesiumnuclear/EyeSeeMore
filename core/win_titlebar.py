# ==========================================
#  core/win_titlebar.py
#  EyeSeeMore — 自定義標題列 DLL 橋接模組
#
#  職責：
#   1. 從 build/ 或應用根目錄載入 EyeSeeMoreWin.dll
#   2. 提供 install() / update_button_rects() / uninstall() 三個函式
#   3. DLL 不存在時降級為 no-op，程式以「系統標題列」模式正常執行
#
#  設計書參考：DESIGN_CustomTitleBar.md §5
# ==========================================

import sys
import os
import ctypes

from core.paths import BASE_DIR

# ──────────────────────────────────────────
#  DLL 搜尋路徑
#  優先順序：根目錄（發佈版）→ build/ 子目錄（開發版）
# ──────────────────────────────────────────
_DLL_NAME = "EyeSeeMoreWin.dll"
_DLL_SEARCH_PATHS = [
    os.path.join(BASE_DIR, _DLL_NAME),
    os.path.join(BASE_DIR, "build", _DLL_NAME),
]

# ──────────────────────────────────────────
#  模組層級狀態
# ──────────────────────────────────────────
_dll = None          # ctypes.CDLL 實例
_installed = False   # 是否已成功安裝 WndProc 掛鉤
_hwnd: int = 0       # 已安裝掛鉤的 HWND

# ──────────────────────────────────────────
#  自定義系統選單項目 ID 常數（與 C++ 端同步）
# ──────────────────────────────────────────
IDM_PAUSE_SCAN  = 0xA000  # 暫停 / 繼續 掃描圖片
IDM_CANCEL_SCAN = 0xA001  # 取消掃描


def _load_dll() -> bool:
    """嘗試載入 DLL，成功回傳 True，失敗靜默回傳 False。"""
    global _dll

    if _dll is not None:
        return True

    if sys.platform != "win32":
        return False

    for path in _DLL_SEARCH_PATHS:
        if os.path.exists(path):
            try:
                _dll = ctypes.CDLL(path)
                _configure_abi()
                print(f"[WinTitlebar] 已載入 DLL：{path}")
                return True
            except Exception as e:
                print(f"[WinTitlebar] 載入 DLL 失敗 ({path})：{e}")
                _dll = None

    print("[WinTitlebar] 找不到 EyeSeeMoreWin.dll，以降級模式運行（系統標題列）")
    return False


def _configure_abi():
    """
    宣告每個匯出函式的 argtypes 與 restype。
    明確宣告是避免 ctypes 預設 c_int 導致 64-bit 指標截斷的關鍵。
    """
    # ESM_InstallHook(HWND hwnd, int titlebar_height, float dpr) -> int
    _dll.ESM_InstallHook.argtypes = [
        ctypes.c_void_p,   # HWND（64-bit 指標，c_void_p 完整保留）
        ctypes.c_int,      # titlebar_height
        ctypes.c_float,    # dpr
    ]
    _dll.ESM_InstallHook.restype = ctypes.c_int

    # ESM_SetButtonRects(16 x int) -> void
    _dll.ESM_SetButtonRects.argtypes = [ctypes.c_int] * 16
    _dll.ESM_SetButtonRects.restype  = None

    # ESM_UninstallHook(HWND hwnd) -> void
    _dll.ESM_UninstallHook.argtypes = [ctypes.c_void_p]
    _dll.ESM_UninstallHook.restype  = None

    # ESM_SetMenuState(int item_id, BOOL checked) -> void
    _dll.ESM_SetMenuState.argtypes = [ctypes.c_int, ctypes.c_bool]
    _dll.ESM_SetMenuState.restype  = None


# ──────────────────────────────────────────
#  公開 API
# ──────────────────────────────────────────

def install(hwnd: int, titlebar_height: int = 60, dpr: float = 1.0) -> bool:
    """
    安裝 WndProc 掛鉤。

    :param hwnd:             PyQt6 視窗的 int(self.winId())
    :param titlebar_height:  TopBar 邏輯像素高度
    :param dpr:              self.devicePixelRatioF()
    :return:                 True = 成功，False = 降級（程式仍可正常運行）
    """
    global _installed, _hwnd

    if not _load_dll():
        return False

    if _installed:
        return True

    try:
        ret = _dll.ESM_InstallHook(
            ctypes.c_void_p(hwnd),
            ctypes.c_int(titlebar_height),
            ctypes.c_float(dpr),
        )
        if ret == 0:
            _installed = True
            _hwnd = hwnd
            print(f"[WinTitlebar] WndProc 掛鉤安裝成功 (HWND={hwnd:#x})")
            return True
        else:
            print(f"[WinTitlebar] ESM_InstallHook 回傳錯誤碼：{ret}")
            return False
    except Exception as e:
        print(f"[WinTitlebar] install() 例外：{e}")
        return False


def update_button_rects(
    min_rect:   tuple | None,
    max_rect:   tuple | None,
    close_rect: tuple | None,
    pin_rect:   tuple | None = None,
):
    """
    更新四個按鈕的感應座標（相對於 MainWindow 客戶端座標，
    **實體像素**——呼叫端已乘上 devicePixelRatio）。

    :param min_rect:   (x, y, width, height)  最小化按鈕
    :param max_rect:   (x, y, width, height)  最大化按鈕
    :param close_rect: (x, y, width, height)  關閉按鈕
    :param pin_rect:   (x, y, width, height)  釘選按鈕（可選）
    """
    if not _installed or _dll is None:
        return

    def _r(t):
        """確保回傳 (x, y, w, h) 四個整數；None 則回傳全零。"""
        if t and len(t) == 4:
            return (int(t[0]), int(t[1]), int(t[2]), int(t[3]))
        return (0, 0, 0, 0)

    cl, ct, cw, ch = _r(close_rect)
    ml, mt, mw, mh = _r(max_rect)
    nl, nt, nw, nh = _r(min_rect)
    pl, pt, pw, ph = _r(pin_rect)

    try:
        _dll.ESM_SetButtonRects(
            cl, ct, cw, ch,
            ml, mt, mw, mh,
            nl, nt, nw, nh,
            pl, pt, pw, ph,
        )
    except Exception as e:
        print(f"[WinTitlebar] update_button_rects() 例外：{e}")


def uninstall(hwnd: int):
    """還原原始 WndProc（MainWindow.closeEvent 時呼叫）。"""
    global _installed, _hwnd

    if not _installed or _dll is None:
        return

    try:
        _dll.ESM_UninstallHook(ctypes.c_void_p(hwnd))
        _installed = False
        _hwnd = 0
        print("[WinTitlebar] WndProc 掛鉤已移除")
    except Exception as e:
        print(f"[WinTitlebar] uninstall() 例外：{e}")


def is_installed() -> bool:
    return _installed


def set_menu_state(item_id: int, checked: bool) -> None:
    """
    更新系統選單項目的勾選符號狀態。

    :param item_id:  IDM_PAUSE_SCAN 或 IDM_CANCEL_SCAN
    :param checked:  True = 顯示勾選符號，False = 移除勾選符號
    """
    if not _installed or _dll is None:
        return
    try:
        _dll.ESM_SetMenuState(ctypes.c_int(item_id), ctypes.c_bool(checked))
    except Exception as e:
        print(f"[WinTitlebar] set_menu_state() 例外：{e}")
