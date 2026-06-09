"""
core/win_event_filters.py
─────────────────────────
Win32 原生事件過濾器與相關工具函式。

包含：
  - Win32 訊息常數（_WM_MAX_HOVER 等）
  - ctypes 結構體（_COPYDATASTRUCT, _COM_GUID, _COM_PROPKEY, _COM_PROPVARIANT, _MSG）
  - COM 工具函式（_com_guid, _com_vtcall, _com_release, _com_lpwstr_pv）
  - AppUserModelID 設定函式（_set_window_aumi）
  - Jump List 注冊函式（_register_jump_list）
  - 系統選單注入函式（_install_sys_menu）
  - 跨進程指令傳送函式（_send_esm_cmd）
  - class WinMaxHoverFilter
  - class WinScanCtrlFilter

零 UI 依賴：只使用 PyQt6.QtCore。
"""

import os
import sys
import ctypes

from PyQt6.QtCore import QAbstractNativeEventFilter

# ── 應用程式識別常數 ──────────────────────────────────────────────────────────
WINDOW_TITLE          = "EyeSeeMore-(Alpha)"
_APP_USER_MODEL_ID    = "EyeSeeMore.Main.v1"  # AppUserModelID（讓 Windows 識別是同一 App）

# ── WinMaxBtn NC hover 通知機制 ──────────────────────────────────────────────
# DLL 在 WM_NCMOUSEMOVE/WM_NCMOUSELEAVE 時發送 WM_APP+1 至視窗訊息佇列。
# Python 端用 QAbstractNativeEventFilter 攔截，再透過 Qt property 刷新 QSS。
_WM_MAX_HOVER   = 0x8001  # WM_APP + 1
_WM_PAUSE_SCAN  = 0x8002  # WM_APP + 2 — DLL 送出的暫停/繼續通知
_WM_CANCEL_SCAN = 0x8003  # WM_APP + 3 — DLL 送出的取消掃描通知
_WM_SYSCOMMAND  = 0x0112  # WM_SYSCOMMAND — 系統選單/標題列右鍵指令
_WM_COPYDATA    = 0x004A  # WM_COPYDATA   — 跨進程傳訊（跳躍清單次要實例使用）
_IDM_PAUSE_SCAN  = 0xA000  # 自定義系統選單項目 ID：暫停 / 繼續（與 C++ 端同步）
_IDM_CANCEL_SCAN = 0xA001  # 自定義系統選單項目 ID：取消掃描（與 C++ 端同步）
_ESM_MAGIC      = 0x45534D43   # WM_COPYDATA dwData 魔術字 'ESMC'
_sys_menu_injected    = False  # 防止重複注入的旗標

# 執行期設定 AppUserModelID，讓跳躍清單能與工作列圖示正確綁定
if sys.platform == 'win32':
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_USER_MODEL_ID)
    except Exception:
        pass

class _COPYDATASTRUCT(ctypes.Structure):
    """WM_COPYDATA 的 lParam 結構，用於跨進程傳遞指令字串。"""
    _fields_ = [
        ('dwData', ctypes.c_size_t),   # 魔術字，識別發送者
        ('cbData', ctypes.c_ulong),    # lpData 的位元組長度
        ('lpData', ctypes.c_void_p),   # 指向資料（Windows 自動複製到接收端地址空間）
    ]

def _send_esm_cmd(cmd: str) -> bool:
    """
    找到正在執行的 EyeSeeMore 視窗，透過 WM_COPYDATA 傳送指令字串。
    由跳躍清單次要實例呼叫，傳送完畢後主呼叫端應立即 sys.exit(0)。
    cmd : 'pause' 或 'cancel'

    注意：lParam 必須宣告為 c_ssize_t（64-bit 有號指標），否則 ctypes 預設
    truncate 成 32-bit c_int，導致高位元被截掉、WM_COPYDATA 傳到錯誤位址。
    """
    if sys.platform != 'win32':
        return False
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype  = ctypes.c_void_p
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.SendMessageW.argtypes = [
            ctypes.c_void_p,   # HWND
            ctypes.c_uint,     # Msg
            ctypes.c_size_t,   # wParam (WPARAM = UINT_PTR)
            ctypes.c_ssize_t,  # lParam (LPARAM = LONG_PTR) — 64-bit 必要！
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if not hwnd:
            print(f"[ESM-Cmd] 找不到視窗 '{WINDOW_TITLE}'")
            return False
        data = cmd.encode('utf-16-le')
        buf  = ctypes.create_string_buffer(data)
        cds  = _COPYDATASTRUCT()
        cds.dwData = _ESM_MAGIC
        cds.cbData = len(data)
        cds.lpData = ctypes.cast(buf, ctypes.c_void_p).value
        user32.SendMessageW(hwnd, _WM_COPYDATA, 0, ctypes.addressof(cds))
        return True
    except Exception as e:
        print(f"[ESM-Cmd] 傳送失敗：{e}")
        return False

# ── 模組層級 COM 工具（Jump List 與視窗 AUMI 共用）────────────────────────────
_COM_S_OK = 0

class _COM_GUID(ctypes.Structure):
    """Windows GUID / CLSID / IID（128 bits）。"""
    _fields_ = [('d1', ctypes.c_ulong), ('d2', ctypes.c_ushort),
                ('d3', ctypes.c_ushort), ('d4', ctypes.c_ubyte * 8)]

def _com_guid(d1, d2, d3, *d4):
    g = _COM_GUID(); g.d1, g.d2, g.d3 = d1, d2, d3
    for i, b in enumerate(d4): g.d4[i] = b
    return g

class _COM_PROPKEY(ctypes.Structure):
    """PROPERTYKEY = {GUID fmtid; DWORD pid}。"""
    _fields_ = [('fmtid', _COM_GUID), ('pid', ctypes.c_ulong)]

class _COM_PROPVARIANT(ctypes.Structure):
    """
    PROPVARIANT（x64 = 24 bytes）。
    vt + 3×reserved = 8 bytes；union（val1 + val2）= 16 bytes。
    """
    _fields_ = [
        ('vt',   ctypes.c_ushort),
        ('r1',   ctypes.c_ushort),
        ('r2',   ctypes.c_ushort),
        ('r3',   ctypes.c_ushort),
        ('val1', ctypes.c_void_p),   # VT_LPWSTR → 字串指標
        ('val2', ctypes.c_void_p),   # 次要值（blob / array 用）
    ]
_COM_VT_LPWSTR = 31

def _com_vtcall(ptr: int, idx: int, restype, *argtypes):
    """呼叫 COM 介面 vtable[idx] 方法，回傳可呼叫的 lambda。"""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    fp   = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[idx]
    fn   = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(fp)
    p    = ctypes.c_void_p(ptr)
    return lambda *args: fn(p, *args)

def _com_release(ptr: int):
    if ptr: _com_vtcall(ptr, 2, ctypes.c_ulong)()

def _com_lpwstr_pv(text: str):
    """建立 VT_LPWSTR PROPVARIANT。回傳 (pv, buf)，呼叫端必須保持 buf 存活。"""
    buf = ctypes.create_unicode_buffer(text)
    pv  = _COM_PROPVARIANT()
    pv.vt   = _COM_VT_LPWSTR
    pv.val1 = ctypes.cast(buf, ctypes.c_void_p).value
    return pv, buf

# ── 視窗 AppUserModelID 注入 ──────────────────────────────────────────────────
def _set_window_aumi(hwnd: int) -> None:
    """
    對視窗 HWND 設定 PKEY_AppUserModel_ID（透過 SHGetPropertyStoreForWindow）。
    這是讓工作列將此視窗歸類為「EyeSeeMore」而非「python.exe」的關鍵步驟；
    唯有設定後，工作列右鍵才會顯示我們注冊的跳躍清單任務。
    """
    if sys.platform != 'win32':
        return
    try:
        _sh = ctypes.windll.shell32
        _sh.SHGetPropertyStoreForWindow.restype  = ctypes.HRESULT
        _sh.SHGetPropertyStoreForWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_COM_GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        IID_PS = _com_guid(0x886D8EEB,0x8CF2,0x4446,0x8D,0x02,0xCD,0xBA,0x1D,0xBD,0xCF,0x99)
        ps = ctypes.c_void_p(0)
        hr = _sh.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(IID_PS), ctypes.byref(ps))
        if hr != _COM_S_OK or not ps.value:
            print(f"[AUMI] SHGetPropertyStoreForWindow hr=0x{hr&0xFFFFFFFF:08X}")
            return
        # PKEY_AppUserModel_ID = {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}, pid=5
        pkey = _COM_PROPKEY()
        pkey.fmtid = _com_guid(0x9F4C2855,0x9F79,0x4B39,0xA8,0xD0,0xE1,0xD4,0x2D,0xE1,0xD5,0xF3)
        pkey.pid   = 5
        pv, buf = _com_lpwstr_pv(_APP_USER_MODEL_ID)
        _com_vtcall(ps.value, 6, ctypes.HRESULT,
                    ctypes.POINTER(_COM_PROPKEY),
                    ctypes.POINTER(_COM_PROPVARIANT))(
            ctypes.byref(pkey), ctypes.byref(pv))
        _com_vtcall(ps.value, 7, ctypes.HRESULT)()   # IPropertyStore::Commit
        _com_release(ps.value)
        print(f"[AUMI] 視窗 AUMI 已設定 → {_APP_USER_MODEL_ID}")
    except Exception as e:
        print(f"[AUMI] 設定視窗 AUMI 失敗：{e}")

# ── Windows 工作列右鍵跳躍清單（Jump List）──────────────────────────────────
def _register_jump_list() -> None:
    """
    向 Windows 工作列右鍵跳躍清單的「工作 (Tasks)」區段加入兩個項目：
      ‧ 暫停 / 繼續 掃描
      ‧ 取消掃描
    點擊後以 --esm-cmd=pause / --esm-cmd=cancel 啟動次要實例，
    次要實例透過 WM_COPYDATA 把指令傳給主實例後立刻退出。
    """
    if sys.platform != 'win32':
        return
    try:
        _do_register_jump_list()
    except Exception as e:
        print(f"[JumpList] 注冊失敗：{e}")

def _do_register_jump_list() -> None:
    """ICustomDestinationList COM vtable 實作（不依賴 pywin32 / comtypes）。"""
    _ol = ctypes.windll.ole32
    _ol.CoCreateInstance.restype  = ctypes.HRESULT
    _ol.CoCreateInstance.argtypes = [
        ctypes.POINTER(_COM_GUID), ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(_COM_GUID), ctypes.POINTER(ctypes.c_void_p),
    ]

    def _cc(clsid, iid) -> int:
        p  = ctypes.c_void_p(0)
        hr = _ol.CoCreateInstance(ctypes.byref(clsid), None, 1,
                                   ctypes.byref(iid), ctypes.byref(p))
        if hr != _COM_S_OK or not p.value:
            raise RuntimeError(f"CoCreateInstance hr=0x{hr&0xFFFFFFFF:08X}")
        return p.value

    CLSID_DL = _com_guid(0x77F10CF0,0x3DB5,0x4966,0xB5,0x20,0xB7,0xC5,0x4F,0xD3,0x5E,0xD6)
    IID_DL   = _com_guid(0x6332DEBF,0x87B5,0x4670,0x90,0xC0,0x5E,0x57,0xB4,0x08,0xA4,0x9E)
    CLSID_OC = _com_guid(0x2D3468C1,0x36A7,0x43B6,0xAC,0x24,0xD3,0xF0,0x2F,0xD9,0x60,0x7A)
    IID_OC   = _com_guid(0x5632B1A4,0xE38A,0x400A,0x92,0x8A,0xD4,0xCD,0x63,0x23,0x02,0x95)
    IID_OA   = _com_guid(0x92CA9DCD,0x5622,0x4BBA,0xA8,0x05,0x5E,0x9F,0x54,0x1B,0xD8,0xC9)
    CLSID_SL = _com_guid(0x00021401,0x0000,0x0000,0xC0,0x00,0x00,0x00,0x00,0x00,0x00,0x46)
    IID_SL   = _com_guid(0x000214F9,0x0000,0x0000,0xC0,0x00,0x00,0x00,0x00,0x00,0x00,0x46)
    IID_PS   = _com_guid(0x886D8EEB,0x8CF2,0x4446,0x8D,0x02,0xCD,0xBA,0x1D,0xBD,0xCF,0x99)
    PKEY_Title = _COM_PROPKEY()
    PKEY_Title.fmtid = _com_guid(0xF29F85E0,0x4FF9,0x1068,0xAB,0x91,0x08,0x00,0x2B,0x27,0xB3,0xD9)
    PKEY_Title.pid   = 2

    py_exe  = sys.executable
    pythonw = os.path.join(os.path.dirname(py_exe), 'pythonw.exe')
    if os.path.exists(pythonw):
        py_exe = pythonw
    script   = os.path.abspath(__file__)
    work_dir = os.path.dirname(script)

    # ICustomDestinationList
    cdl = _cc(CLSID_DL, IID_DL)
    hr = _com_vtcall(cdl, 3, ctypes.HRESULT, ctypes.c_wchar_p)(_APP_USER_MODEL_ID)
    if hr != _COM_S_OK:
        _com_release(cdl)
        raise RuntimeError(f"SetAppID hr=0x{hr&0xFFFFFFFF:08X}")

    nSlots  = ctypes.c_uint(0)
    removed = ctypes.c_void_p(0)
    _com_vtcall(cdl, 4, ctypes.HRESULT,
                ctypes.POINTER(ctypes.c_uint),
                ctypes.POINTER(_COM_GUID),
                ctypes.POINTER(ctypes.c_void_p))(
        ctypes.byref(nSlots), ctypes.byref(IID_OA), ctypes.byref(removed))
    _com_release(removed.value)

    oc = _cc(CLSID_OC, IID_OC)

    def _make_task(title: str, flag: str):
        try:
            sl = _cc(CLSID_SL, IID_SL)
        except Exception:
            return None
        args_str = f'"{script}" {flag}'
        _com_vtcall(sl, 20, ctypes.HRESULT, ctypes.c_wchar_p)(py_exe)     # SetPath (vtable[20])
        _com_vtcall(sl, 11, ctypes.HRESULT, ctypes.c_wchar_p)(args_str)   # SetArguments
        _com_vtcall(sl,  9, ctypes.HRESULT, ctypes.c_wchar_p)(work_dir)   # SetWorkingDirectory
        _com_vtcall(sl, 15, ctypes.HRESULT, ctypes.c_int)(0)              # SetShowCmd(SW_HIDE)
        _com_vtcall(sl, 17, ctypes.HRESULT,
                    ctypes.c_wchar_p, ctypes.c_int)(py_exe, 0)             # SetIconLocation
        # IPropertyStore::SetValue(PKEY_Title) — 設定顯示文字
        ps = ctypes.c_void_p(0)
        hr2 = _com_vtcall(sl, 0, ctypes.HRESULT,
                          ctypes.POINTER(_COM_GUID),
                          ctypes.POINTER(ctypes.c_void_p))(
            ctypes.byref(IID_PS), ctypes.byref(ps))
        if hr2 == _COM_S_OK and ps.value:
            pv, buf = _com_lpwstr_pv(title)
            _com_vtcall(ps.value, 6, ctypes.HRESULT,
                        ctypes.POINTER(_COM_PROPKEY),
                        ctypes.POINTER(_COM_PROPVARIANT))(
                ctypes.byref(PKEY_Title), ctypes.byref(pv))
            _com_vtcall(ps.value, 7, ctypes.HRESULT)()   # Commit
            _com_release(ps.value)
        return sl

    for title, flag in [
        ("暫停 / 繼續 掃描", "--esm-cmd=pause"),
        ("取消掃描",         "--esm-cmd=cancel"),
    ]:
        sl_ptr = _make_task(title, flag)
        if sl_ptr:
            _com_vtcall(oc, 5, ctypes.HRESULT, ctypes.c_void_p)(sl_ptr)  # AddObject
            _com_release(sl_ptr)

    _com_vtcall(cdl, 7, ctypes.HRESULT, ctypes.c_void_p)(oc)   # AddUserTasks
    hr = _com_vtcall(cdl, 8, ctypes.HRESULT)()                  # CommitList
    _com_release(oc)
    _com_release(cdl)
    print(f"[JumpList] 已注冊（CommitList hr=0x{hr&0xFFFFFFFF:08X}）")

def _install_sys_menu(hwnd: int) -> None:
    """
    直接從 Python 向視窗的系統選單（右鍵標題列 / Alt+Space）注入自定義項目。

    ‧ 不需要 EyeSeeMoreWin.dll，作為 DLL 未編譯時的完整降級方案。
    ‧ 若 DLL 已安裝（_wt._installed == True），代表 C++ 端已呼叫過 AppendMenuW，
      此函式直接返回，避免重複插入。
    ‧ 注入後的項目會觸發 WM_SYSCOMMAND；WinScanCtrlFilter 負責攔截並轉發。

    注意：這些項目出現在「右鍵標題列」或按下 Alt+Space 的視窗選單中，
    並非 Windows 11 工作列右鍵的跳躍清單（Jump List）。
    """
    global _sys_menu_injected
    if sys.platform != 'win32' or _sys_menu_injected:
        return
    # 若 DLL 已成功安裝，C++ 端已插入選單，跳過
    try:
        from core import win_titlebar as _wt
        if _wt._installed:
            _sys_menu_injected = True
            return
    except Exception:
        pass

    try:
        user32 = ctypes.windll.user32
        MF_SEPARATOR = 0x800
        MF_STRING    = 0x0
        hSysMenu = user32.GetSystemMenu(hwnd, False)
        if hSysMenu:
            user32.AppendMenuW(hSysMenu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(hSysMenu, MF_STRING, _IDM_PAUSE_SCAN,  "暫停 / 繼續 掃描圖片")
            user32.AppendMenuW(hSysMenu, MF_STRING, _IDM_CANCEL_SCAN, "取消掃描")
            _sys_menu_injected = True
            print("[SysMenu] 系統選單項目已從 Python 端注入（右鍵標題列 / Alt+Space 可見）")
    except Exception as e:
        print(f"[SysMenu] 注入失敗：{e}")

class _MSG(ctypes.Structure):
    """Windows MSG 結構，供 nativeEventFilter 解析。"""
    _fields_ = [
        ('hwnd',    ctypes.c_void_p),
        ('message', ctypes.c_uint),
        ('wParam',  ctypes.c_size_t),
        ('lParam',  ctypes.c_ssize_t),
        ('time',    ctypes.c_ulong),
        ('pt_x',    ctypes.c_long),
        ('pt_y',    ctypes.c_long),
    ]

class WinMaxHoverFilter(QAbstractNativeEventFilter):
    """攔截 DLL 的 WM_APP+1，通知 WinMaxBtn 刷新 NC hover 外觀。"""
    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
            if msg.message == _WM_MAX_HOVER:
                self._cb(bool(msg.wParam))
        return False, 0


class WinScanCtrlFilter(QAbstractNativeEventFilter):
    """
    攔截以下三類訊息，統一轉發給 MainWindow 的控制方法：

    1. WM_APP+2 / WM_APP+3 (0x8002 / 0x8003)：
       EyeSeeMoreWin.dll 安裝時，DLL HookWndProc 截取 WM_SYSCOMMAND 後
       以 PostMessageW 轉發。

    2. WM_SYSCOMMAND (0x0112)：
       DLL 未安裝時，_install_sys_menu() 直接注入系統選單；
       點擊後 Windows 直接發 WM_SYSCOMMAND（右鍵標題列 / Alt+Space）。

    3. WM_COPYDATA (0x004A)：
       工作列右鍵跳躍清單任務點擊後啟動次要實例，
       次要實例透過 SendMessage(WM_COPYDATA) 傳送 'pause'/'cancel' 字串。
    """
    def __init__(self, pause_cb, cancel_cb):
        super().__init__()
        self._pause_cb  = pause_cb
        self._cancel_cb = cancel_cb

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
            m = msg.message
            if m == _WM_PAUSE_SCAN:
                self._pause_cb()
            elif m == _WM_CANCEL_SCAN:
                self._cancel_cb()
            elif m == _WM_SYSCOMMAND:
                # 使用精確比對（不用 & 0xFFF0 mask）。
                # & 0xFFF0 mask 僅適用於 SC_* 系統指令；
                # IDM_PAUSE_SCAN=0xA000 / IDM_CANCEL_SCAN=0xA001 北天確別
                if msg.wParam == _IDM_PAUSE_SCAN:
                    self._pause_cb()
                    return True, 0
                elif msg.wParam == _IDM_CANCEL_SCAN:
                    self._cancel_cb()
                    return True, 0
            elif m == _WM_COPYDATA:
                try:
                    cds = ctypes.cast(msg.lParam, ctypes.POINTER(_COPYDATASTRUCT)).contents
                    if cds.dwData == _ESM_MAGIC and cds.lpData and cds.cbData > 0:
                        raw = (ctypes.c_byte * cds.cbData).from_address(cds.lpData)
                        cmd = bytes(raw).decode('utf-16-le').strip('\x00')
                        if cmd == 'pause':
                            self._pause_cb()
                        elif cmd == 'cancel':
                            self._cancel_cb()
                        return True, 0
                except Exception:
                    pass
        return False, 0
