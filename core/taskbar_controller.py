import sys
import ctypes
from ctypes import wintypes

# 定義 Windows 工作列狀態常數
TBPF_NOPROGRESS = 0       # 隱藏 / 恢復正常
TBPF_INDETERMINATE = 0x1  # 綠色流光 (載入中)
TBPF_NORMAL = 0x2         # 綠色進度條 (處理中)
TBPF_ERROR = 0x4          # 紅色進度條 (發生錯誤)
TBPF_PAUSED = 0x8         # 黃色進度條 (暫停)

if sys.platform == 'win32':
    ole32 = ctypes.windll.ole32

    # 定義 GUID 結構
    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8)
        ]

    # ITaskbarList3 的虛擬函數表 (VTable)
    class ITaskbarList3Vtbl(ctypes.Structure):
        _fields_ = [
            ("QueryInterface", ctypes.c_void_p),
            ("AddRef", ctypes.c_void_p),
            ("Release", ctypes.c_void_p),
            ("HrInit", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)),
            ("AddTab", ctypes.c_void_p),
            ("DeleteTab", ctypes.c_void_p),
            ("ActivateTab", ctypes.c_void_p),
            ("SetActiveAlt", ctypes.c_void_p),
            ("MarkFullscreenWindow", ctypes.c_void_p),
            # [關鍵] 設定進度條數值的函數指標
            ("SetProgressValue", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND, ctypes.c_uint64, ctypes.c_uint64)),
            # [關鍵] 設定進度條狀態的函數指標
            ("SetProgressState", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND, ctypes.c_int)),
            ("RegisterTab", ctypes.c_void_p),
            ("UnregisterTab", ctypes.c_void_p),
            ("SetTabOrder", ctypes.c_void_p),
            ("SetTabActive", ctypes.c_void_p),
            ("ThumbBarAddButtons", ctypes.c_void_p),
            ("ThumbBarUpdateButtons", ctypes.c_void_p),
            ("ThumbBarSetImageList", ctypes.c_void_p),
            ("SetOverlayIcon", ctypes.c_void_p),
            ("SetThumbnailTooltip", ctypes.c_void_p),
            ("SetThumbnailClip", ctypes.c_void_p)
        ]

    class ITaskbarList3(ctypes.Structure):
        _fields_ = [("lpVtbl", ctypes.POINTER(ITaskbarList3Vtbl))]

    # CLSID 與 IID 定義
    CLSID_TaskbarList = GUID(0x56FDF344, 0xFD6D, 0x11d0, (0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90))
    IID_ITaskbarList3 = GUID(0xEA1AFB91, 0x9E28, 0x4B86, (0x90, 0xE9, 0x9E, 0x9F, 0x8A, 0x5E, 0xEF, 0xAF))


class TaskbarController:
    """用來控制 Windows 工作列圖示的萬能控制器"""
    def __init__(self, window_id):
        self.hwnd = int(window_id)  # 取得 PyQt 視窗的底層 HWND
        self.taskbar = None
        if sys.platform == 'win32':
            self._init_com()

    def _init_com(self):
        try:
            # 確保 COM 被初始化
            ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED

            # 建立 ITaskbarList3 實例
            obj = ctypes.POINTER(ITaskbarList3)()
            hr = ole32.CoCreateInstance(
                ctypes.byref(CLSID_TaskbarList),
                None,
                1,  # CLSCTX_INPROC_SERVER
                ctypes.byref(IID_ITaskbarList3),
                ctypes.byref(obj)
            )

            if hr == 0:
                self.taskbar = obj
                # 呼叫 HrInit 啟用工作列控制
                self.taskbar.contents.lpVtbl.contents.HrInit(self.taskbar)
        except Exception as e:
            print(f"Taskbar init error: {e}")

    def set_state(self, state_code):
        """切換進度條狀態 (如綠色、紅色、流光)"""
        if self.taskbar:
            self.taskbar.contents.lpVtbl.contents.SetProgressState(self.taskbar, self.hwnd, state_code)

    def set_progress(self, current, total):
        """設定進度條百分比"""
        if self.taskbar and total > 0:
            self.taskbar.contents.lpVtbl.contents.SetProgressValue(self.taskbar, self.hwnd, current, total)
