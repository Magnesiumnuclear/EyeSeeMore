"""
WindowStateManager  –  視窗狀態與 Win32 原生整合管理器
=========================================================
從 MainWindow 抽離的職責：
  • 視窗釘選（TOPMOST）：Win32 SetWindowPos 切換 + 持久化設定
  • 最大化 / 還原：showMaximized / showNormal + 按鈕圖示同步
  • NC 區 Hover 補丁：DLL WM_APP+1 → btn_max nc_hover 屬性刷新
  • WndProc Hook 按鈕命中座標通知（無邊框視窗 NC hit-test 必要）
  • saveGeometry / restoreGeometry 的封裝（含預設 fallback 與例外處理）
  • Win32 資源回收（移除 native event filter + 卸載 WndProc Hook）

設計原則：
  • 繼承 QObject，但**不發射訊號**——本控制器直接操作注入的按鈕與視窗，
    因為這些操作都是 Win32/Qt 視窗系統層級的整合，沒有訂閱者需要解耦
  • 依賴注入：window + 4 個視窗控制按鈕 + config（不持有任何 MainWindow
    內部狀態的耦合）
  • 與 core/win_titlebar 模組緊密協作（自訂標題列 DLL Hook）

使用方式：
    mgr = WindowStateManager(
        mw, mw.config,
        btn_pin=mw.btn_pin, btn_max=mw.btn_win_max,
        btn_min=mw.btn_win_min, btn_close=mw.btn_win_close,
    )
    # 安裝 native filter 後告知 manager 以便 uninstall 時清除
    mgr.attach_native_filter(WinMaxHoverFilter(mgr._on_max_btn_hover))
    mgr.restore_geometry()

    # resizeEvent
    mgr.sync_max_button_state()
    mgr.update_button_rects()

    # closeEvent
    mgr.save_geometry_into(ui_state)
    mgr.uninstall()
"""

from __future__ import annotations

import ctypes
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QByteArray, QObject, Qt
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton

if TYPE_CHECKING:
    from PyQt6.QtCore import QAbstractNativeEventFilter
    from core.config_manager import ConfigManager


class WindowStateManager(QObject):
    """視窗狀態與 Win32 整合的獨立管理器。

    封裝原本散落在 MainWindow 內的視窗釘選、最大化、NC hit-test 座標
    通知、幾何持久化等邏輯。所有 Win32 ctypes 呼叫與 win_titlebar Hook
    交互都集中在此處，MainWindow 透過 thin delegate 維持向後相容。
    """

    # ── Win32 SetWindowPos 常數 ──────────────────────────────────────
    _HWND_TOPMOST = ctypes.c_void_p(-1)
    _HWND_NOTOPMOST = ctypes.c_void_p(-2)
    _SWP_NOMOVE_NOSIZE = 0x0003  # SWP_NOMOVE | SWP_NOSIZE
    _SWP_NOACTIVATE = 0x0010

    def __init__(
        self,
        window: QMainWindow,
        config: "ConfigManager",
        *,
        btn_pin: QPushButton,
        btn_max: QPushButton,
        btn_min: QPushButton,
        btn_close: QPushButton,
    ) -> None:
        """建立 WindowStateManager 實例。

        Args:
            window: 被管理的 QMainWindow。
            config: ConfigManager，用於讀寫 ui_state.always_on_top / geometry 等。
            btn_pin: 釘選（TOPMOST）按鈕（toggled signal 會自動接到內部 slot）。
            btn_max: 最大化／還原按鈕（toggled signal 會自動接到內部 slot）。
            btn_min: 最小化按鈕（用於通知 WndProc 命中座標）。
            btn_close: 關閉按鈕（用於通知 WndProc 命中座標）。
        """
        super().__init__(window)
        self.window: QMainWindow = window
        self.config: "ConfigManager" = config
        self.btn_pin: QPushButton = btn_pin
        self.btn_max: QPushButton = btn_max
        self.btn_min: QPushButton = btn_min
        self.btn_close: QPushButton = btn_close

        #: 由外部建立並 attach 的 NC hover native filter（uninstall 時用）
        self._max_hover_filter: Optional["QAbstractNativeEventFilter"] = None

        # 連接按鈕事件 + 還原初始狀態
        self.btn_pin.toggled.connect(self._on_pin_toggled)
        self.btn_max.toggled.connect(self._on_win_max_toggled)
        self._init_button_states()

    # ------------------------------------------------------------------
    #  初始按鈕狀態還原（從 config / 視窗當前狀態同步到按鈕外觀）
    # ------------------------------------------------------------------
    def _init_button_states(self) -> None:
        """讀取 config 與 window.isMaximized() 設定 pin / max 按鈕初始外觀。

        - 若 ui_state.always_on_top 為 True：設定 WindowStaysOnTopHint flag
          並立刻 show() 視窗（Hook 安裝前用 setWindowFlag 不影響 WndProc）。
        - 若視窗已最大化：同步 btn_max 為 checked + ❐ 圖示。
        """
        # Pin button initial state
        always_on_top = self.config.get("ui_state", {}).get("always_on_top", False)
        if always_on_top:
            # 此時 Hook 尚未安裝，用 setWindowFlag 不影響 HWND 的 WndProc 狀態
            # Hook 安裝後（QTimer 0ms）會在新 HWND 上補裝，維持正常
            self.window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.window.show()
            self.btn_pin.blockSignals(True)
            self.btn_pin.setChecked(True)
            self.btn_pin.setToolTip("取消釘選 (Ctrl+T)")
            self.btn_pin.blockSignals(False)

        # Max button initial state
        if self.window.isMaximized():
            self.btn_max.blockSignals(True)
            self.btn_max.setChecked(True)
            self.btn_max.setText("❐")
            self.btn_max.setToolTip("還原")
            self.btn_max.blockSignals(False)

    # ------------------------------------------------------------------
    #  Native filter 註冊（由 MainWindow 建立後告知 manager 持有參照）
    # ------------------------------------------------------------------
    def attach_native_filter(self, native_filter: "QAbstractNativeEventFilter") -> None:
        """將外部建立的 native filter 交由 manager 管理生命週期。

        外部負責呼叫 QApplication.installNativeEventFilter()；
        manager 會在 uninstall() 時呼叫 removeNativeEventFilter() 清除。

        Args:
            native_filter: 已 install 的 QAbstractNativeEventFilter 實例。
        """
        self._max_hover_filter = native_filter

    # ------------------------------------------------------------------
    #  幾何持久化
    # ------------------------------------------------------------------
    def restore_geometry(self) -> None:
        """從 config.ui_state 還原視窗幾何與 dock state。

        先設定 1280×900 的 fallback 預設尺寸，避免 normalGeometry 在
        restoreGeometry 前為零值（這會導致 unmaximize 時縮不回正確大小）。
        例外靜默處理並印出警告（不阻擋啟動）。
        """
        ui_state = self.config.get("ui_state", {})
        # 先設定合理預設尺寸，確保 normalGeometry 在 restoreGeometry() 前不為零值
        self.window.resize(1280, 900)

        if "geometry" in ui_state and "window_state" in ui_state:
            try:
                ok = self.window.restoreGeometry(
                    QByteArray.fromHex(ui_state["geometry"].encode("ascii"))
                )
                if ok:
                    self.window.restoreState(
                        QByteArray.fromHex(ui_state["window_state"].encode("ascii"))
                    )
                else:
                    print("[WindowStateManager] restoreGeometry 回傳 False，使用預設大小")
            except Exception as e:
                print(f"[WindowStateManager] 視窗狀態還原失敗: {e}")

    def save_geometry_into(self, ui_state: dict) -> None:
        """將當前視窗幾何與 dock state 寫入 ui_state dict（就地修改）。

        採 in-place 模式而非 config.set() 直接寫入，讓 MainWindow.closeEvent
        能將所有持久化欄位（含 sidebar / view_mode 等）原子性地一次 set，
        避免兩次寫入之間出現不一致快照。

        Args:
            ui_state: 待寫入的設定字典。會新增 'geometry' 與 'window_state'
                     兩個欄位，並清除舊版 window_width / window_height /
                     is_maximized 等已被 saveGeometry 涵蓋的欄位。
        """
        ui_state["geometry"] = self.window.saveGeometry().toHex().data().decode("ascii")
        ui_state["window_state"] = self.window.saveState().toHex().data().decode("ascii")
        # 清除已被 saveGeometry() 取代的舊欄位，避免 config.json 殘留臟資料
        for old_key in ["window_width", "window_height", "is_maximized"]:
            ui_state.pop(old_key, None)

    # ------------------------------------------------------------------
    #  resizeEvent 時的同步動作
    # ------------------------------------------------------------------
    def sync_max_button_state(self) -> None:
        """同步 btn_max 按鈕的勾選狀態與圖示（resizeEvent 時呼叫）。

        當使用者透過 Windows 系統選單 / 快捷鍵 / 拖曳邊界等方式變更
        最大化狀態時，btn_max 需要跟著刷新。
        """
        is_max = self.window.isMaximized()
        if self.btn_max.isChecked() != is_max:
            self.btn_max.blockSignals(True)
            self.btn_max.setChecked(is_max)
            self.btn_max.setText("❐" if is_max else "□")
            self.btn_max.setToolTip("還原" if is_max else "最大化")
            self.btn_max.blockSignals(False)

    def update_button_rects(self) -> None:
        """通知 win_titlebar WndProc Hook 四個視窗控制按鈕的命中座標。

        WM_NCHITTEST 的座標為**實體像素**，必須乘以 DPR 才能對應 Qt
        邏輯像素座標。若 Hook 尚未安裝則靜默返回。
        """
        from core import win_titlebar
        if not win_titlebar.is_installed():
            return

        dpr = self.window.devicePixelRatioF()

        def _to_client(btn: QPushButton) -> tuple:
            pos = btn.mapTo(self.window, btn.rect().topLeft())
            return (
                int(pos.x() * dpr), int(pos.y() * dpr),
                int(btn.width() * dpr), int(btn.height() * dpr),
            )

        win_titlebar.update_button_rects(
            min_rect=_to_client(self.btn_min),
            max_rect=_to_client(self.btn_max),
            close_rect=_to_client(self.btn_close),
            pin_rect=_to_client(self.btn_pin),
        )

    # ------------------------------------------------------------------
    #  closeEvent 時的清理動作
    # ------------------------------------------------------------------
    def uninstall(self) -> None:
        """關閉視窗時的 Win32 資源回收：
          1. 從 QApplication 移除 NC hover native filter
          2. 卸載 win_titlebar 的 WndProc Hook，還原系統視窗程序
        """
        if self._max_hover_filter is not None:
            QApplication.instance().removeNativeEventFilter(self._max_hover_filter)
            self._max_hover_filter = None
        from core import win_titlebar
        win_titlebar.uninstall(int(self.window.winId()))

    # ==================================================================
    #  按鈕事件處理（連接於 __init__）
    # ==================================================================
    def _on_pin_toggled(self, checked: bool) -> None:
        """切換視窗 TOPMOST 並持久化 ui_state.always_on_top。

        使用 Win32 SetWindowPos 直接切換，而非 setWindowFlag。
        setWindowFlag 會重建 HWND，導致 WndProc Hook 和 WS_THICKFRAME
        全部失效——這正是無邊框視窗整合最容易踩的坑。

        Args:
            checked: True 表示啟用置頂；False 表示取消置頂。
        """
        hwnd = int(self.window.winId())
        swp_flags = self._SWP_NOMOVE_NOSIZE | self._SWP_NOACTIVATE
        ctypes.windll.user32.SetWindowPos(
            hwnd,
            self._HWND_TOPMOST if checked else self._HWND_NOTOPMOST,
            0, 0, 0, 0,
            swp_flags,
        )

        self.btn_pin.setToolTip(
            "取消釘選 (Ctrl+T)" if checked else "釘選視窗至最上層 (Ctrl+T)"
        )

        ui_state = self.config.get("ui_state", {})
        ui_state["always_on_top"] = checked
        self.config.set("ui_state", ui_state)

    def _on_win_max_toggled(self, checked: bool) -> None:
        """最大化 / 還原視窗，並同步按鈕圖示與 tooltip。

        Args:
            checked: True → 最大化；False → 還原。
        """
        if checked:
            self.window.showMaximized()
            self.btn_max.setText("❐")
            self.btn_max.setToolTip("還原")
        else:
            self.window.showNormal()
            self.btn_max.setText("□")
            self.btn_max.setToolTip("最大化")

    def _on_max_btn_hover(self, hovered: bool) -> None:
        """DLL WM_APP+1 → 刷新 btn_max 的 NC hover 外觀。

        DLL 回傳 HTMAXBUTTON 時 Windows 接管 NC 滑鼠事件，Qt 的 :hover
        虛擬類別不會觸發。改用 WM_APP+1 訊息橋接：DLL 偵測到滑鼠進出
        max 按鈕區 → PostMessage WM_APP+1 → WinMaxHoverFilter → 本方法
        → 設定 nc_hover 屬性 + 強制 unpolish/polish 重繪。

        Args:
            hovered: True 表示滑鼠進入 max 按鈕區；False 表示離開。
        """
        self.btn_max.setProperty("nc_hover", hovered)
        self.btn_max.style().unpolish(self.btn_max)
        self.btn_max.style().polish(self.btn_max)
