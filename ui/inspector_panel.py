# ==========================================
#  inspector_panel.py
#  EyeSeeMore - 右側屬性與檢索控制台
#  從 Blur-main.py 中搬遷而來的完整 InspectorPanel 元件，
#  含 CollapsibleSection 與 RangeCalendarWidget 輔助類別。
# ==========================================

import calendar
import os
import subprocess
from datetime import date, datetime, time as dt_time, timedelta

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QImageReader, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSlider, QTabWidget,
    QVBoxLayout, QWidget,
)


# ==========================================
#  CollapsibleSection — 可摺疊區塊 (仿 VSCode)
# ==========================================

class CollapsibleSection(QWidget):
    """自定義摺疊區塊，仿 VSCode 樣式 (解決文字跳動問題)"""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # 1. 標頭按鈕 (Header) - 這次我們不直接在按鈕上寫字
        self.header = QPushButton()
        self.header.setFixedHeight(36)
        self.header.setCheckable(True)
        self.header.setChecked(True) # 預設展開
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setObjectName("CollapseHeader")
        
        # --- 解決跳動的魔法：在按鈕內部建立專屬 Layout ---
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(12, 8, 12, 8)
        self.header_layout.setSpacing(5) # 箭頭與文字的距離

        # A. 獨立的箭頭標籤
        self.lbl_arrow = QLabel("▼")
        self.lbl_arrow.setFixedWidth(16) # 🔒 鎖死寬度，文字絕對不會亂跑
        self.lbl_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter) # 讓箭頭在 16px 內乖乖置中
        
        # B. 獨立的標題標籤
        self.lbl_title = QLabel(title)
        
        # 統一設定標籤樣式，並讓滑鼠點擊「穿透」標籤，確保按鈕能正常被點擊
        
        self.lbl_arrow.setObjectName("CollapseArrow")
        self.lbl_arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # 把標籤加入按鈕內部
        self.header_layout.addWidget(self.lbl_arrow)
        self.header_layout.addWidget(self.lbl_title)
        self.header_layout.addStretch(1) # 彈簧把文字往左推
        # ------------------------------------------------

        # 2. 內容容器 (Content)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(20, 15, 20, 15)
        self.content_layout.setSpacing(12)
        
        self.layout.addWidget(self.header)
        self.layout.addWidget(self.content)
        
        # 連結點擊事件
        self.header.clicked.connect(self.toggle_content)

    def toggle_content(self):
        is_expanded = self.header.isChecked()
        self.content.setVisible(is_expanded)
        # 程式碼變乾淨了，直接改獨立箭頭的字就好！
        self.lbl_arrow.setText("▼" if is_expanded else "▶")

    def set_expanded(self, expanded: bool):
        self.header.setChecked(expanded)
        self.content.setVisible(expanded)
        self.lbl_arrow.setText("▼" if expanded else "▶")

    def addWidget(self, widget):
        self.content_layout.addWidget(widget)

    def addLayout(self, layout):
        self.content_layout.addLayout(layout)

    def set_status_active(self, is_active):
        """層級二：控制檢索過濾區塊的動態底線"""
        state_str = "true" if is_active else "false"
        self.header.setProperty("active", state_str)
        self.lbl_title.setProperty("active", state_str)
        
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)
        self.lbl_title.style().unpolish(self.lbl_title)
        self.lbl_title.style().polish(self.lbl_title)


# ==========================================
#  RangeCalendarWidget — 進階區間日曆
# ==========================================

class RangeCalendarWidget(QWidget):
    """具備控制列與狀態提示的進階區間日曆"""
    apply_requested = pyqtSignal(date, date)   # 點擊套用結果
    search_requested = pyqtSignal(date, date)  # 點擊直接搜尋
    cleared = pyqtSignal()                     # 點擊清除
    selection_started = pyqtSignal()           # 點第一下時觸發

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.today = date.today()
        self.current_year = self.today.year
        self.current_month = self.today.month
        self.start_date = None
        self.end_date = None
        self.btn_dates_map = {}
        self.setObjectName("RangeCalendar")
        self.init_ui()
        self.update_calendar()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        # 1. 頂部標頭 (年月)
        header_layout = QHBoxLayout()
        self.btn_prev = QPushButton("◀"); self.btn_prev.setFixedSize(28, 28); self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_prev.clicked.connect(self.prev_month)
        self.lbl_month_year = QLabel(""); self.lbl_month_year.setAlignment(Qt.AlignmentFlag.AlignCenter); self.lbl_month_year.setStyleSheet("font-size: 15px;")
        self.btn_next = QPushButton("▶"); self.btn_next.setFixedSize(28, 28); self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.clicked.connect(self.next_month)
        header_layout.addWidget(self.btn_prev); header_layout.addWidget(self.lbl_month_year, stretch=1); header_layout.addWidget(self.btn_next)
        main_layout.addLayout(header_layout)

        # 2. 星期標籤
        # ==========================================
        # 🌟 重構：統一網格化 (星期標籤 + 日期按鈕)
        # ==========================================
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(2)

        # 1. 寫入星期標籤 (放在第 0 列)
        weekdays = ["日", "一", "二", "三", "四", "五", "六"]
        for col, wd in enumerate(weekdays):
            lbl = QLabel(wd)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setObjectName("CalendarWeekday")
            self.grid_layout.addWidget(lbl, 0, col)

        # 2. 寫入日期按鈕 (放在第 1~6 列)
        self.day_buttons = []
        for row in range(1, 7): 
            for col in range(7):
                btn = QPushButton()
                btn.setFixedSize(28, 28)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(self.on_day_clicked)
                self.grid_layout.addWidget(btn, row, col)
                self.day_buttons.append(btn)
                
        main_layout.addLayout(self.grid_layout)

        # 4. 狀態訊息提示區
        self.lbl_status = QLabel("💡 請點選開始與結束日期...")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setObjectName("CalendarStatus")
        self.lbl_status.setProperty("state", "normal")
        main_layout.addWidget(self.lbl_status)

        # 5. 底部控制按鈕區
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 5, 0, 0)
        
        self.btn_clear = QPushButton("清除"); self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setProperty("cssClass", "DangerBtn")
        self.btn_clear.clicked.connect(self.clear_selection)
        
        self.btn_today = QPushButton("今天"); self.btn_today.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_today.setProperty("cssClass", "ActionBtn")
        self.btn_today.clicked.connect(self.go_to_today)

        self.btn_apply = QPushButton("套用結果"); self.btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply.setProperty("cssClass", "ActionBtn")
        self.btn_apply.clicked.connect(lambda: self.apply_requested.emit(self.start_date, self.end_date))
        self.btn_apply.setEnabled(False)

        self.btn_search = QPushButton("直接搜尋"); self.btn_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search.setProperty("cssClass", "ActionBtn")
        self.btn_search.clicked.connect(lambda: self.search_requested.emit(self.start_date, self.end_date))
        self.btn_search.setEnabled(False)

        left_h = QHBoxLayout(); left_h.setSpacing(5)
        left_h.addWidget(self.btn_clear); left_h.addWidget(self.btn_today)
        right_h = QHBoxLayout(); right_h.setSpacing(5)
        right_h.addWidget(self.btn_apply); right_h.addWidget(self.btn_search)

        footer_layout.addLayout(left_h); footer_layout.addStretch(1); footer_layout.addLayout(right_h)
        main_layout.addLayout(footer_layout)

    def set_status(self, text, state="normal"):
        """供外部控制訊息區的文字與顏色"""
        self.lbl_status.setText(text)
        self.lbl_status.setProperty("state", state) #  狀態交給 QSS 判定
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)

    def update_action_buttons(self):
        can_action = bool(self.start_date and self.end_date)
        self.btn_apply.setEnabled(can_action)
        self.btn_search.setEnabled(can_action)
        
        if can_action:
            days = (self.end_date - self.start_date).days + 1
            self.set_status(f"💡 已選取 {days} 天，請選擇動作。", "primary")
        else:
            self.set_status("💡 請點選結束日期...", "normal")

    # ---------------- 內部邏輯與事件 ----------------
    def update_calendar(self):
        self.lbl_month_year.setText(f"{self.current_year} 年 {self.current_month} 月")
        cal = calendar.Calendar(firstweekday=6)
        month_days = cal.monthdatescalendar(self.current_year, self.current_month)
        flat_days = [day for week in month_days for day in week]

        for i, btn in enumerate(self.day_buttons):
            if i < len(flat_days):
                day_obj = flat_days[i]
                btn.setText(str(day_obj.day))
                self.btn_dates_map[btn] = day_obj
                btn.setProperty("is_endpoint", "false"); btn.setProperty("in_range", "false"); btn.setProperty("is_today", "false")

                # 【修改後】改成屬性標記
                is_other = "true" if day_obj.month != self.current_month else "false"
                btn.setProperty("is_other_month", is_other)

                if day_obj == self.today: btn.setProperty("is_today", "true")

                if self.start_date and self.end_date:
                    if day_obj == self.start_date or day_obj == self.end_date: btn.setProperty("is_endpoint", "true")
                    elif self.start_date < day_obj < self.end_date: btn.setProperty("in_range", "true")
                elif self.start_date and day_obj == self.start_date:
                    btn.setProperty("is_endpoint", "true")

                btn.style().unpolish(btn); btn.style().polish(btn)
        
        self.update_action_buttons()

    def on_day_clicked(self):
        btn = self.sender()
        clicked_date = self.btn_dates_map.get(btn)
        if not clicked_date: return

        if self.start_date is None or (self.start_date and self.end_date):
            # 狀態 1：選取第一下 (設定起點)
            self.start_date = clicked_date
            self.end_date = None
            self.selection_started.emit()
        else:
            # 狀態 2：選取第二下 (完成範圍)
            if clicked_date < self.start_date:
                #  【關鍵修正】如果第二下點得比第一下早，自動反轉起訖日！
                self.end_date = self.start_date
                self.start_date = clicked_date
            else:
                # 正常從早點到晚
                self.end_date = clicked_date
                
        self.update_calendar()

    def clear_selection(self):
        self.start_date = None; self.end_date = None
        self.update_calendar()
        self.set_status("💡 請點選開始與結束日期...", "normal")
        self.cleared.emit()

    def go_to_today(self):
        self.current_year = self.today.year; self.current_month = self.today.month
        self.start_date = self.today; self.end_date = self.today
        self.update_calendar()

    def prev_month(self):
        if self.current_month == 1: self.current_month = 12; self.current_year -= 1
        else: self.current_month -= 1
        self.update_calendar()

    def next_month(self):
        if self.current_month == 12: self.current_month = 1; self.current_year += 1
        else: self.current_month += 1
        self.update_calendar()


# ==========================================
#  InspectorPanel — 右側屬性與檢索控制台
# ==========================================

class InspectorPanel(QFrame):
    """右側屬性與檢索控制台 (三層分頁架構)"""

    aspect_changed = pyqtSignal()
    sort_changed = pyqtSignal()
    time_filter_applied = pyqtSignal(float, float) 
    time_search_requested = pyqtSignal(float, float)
    time_filter_cleared = pyqtSignal()
    weights_changed = pyqtSignal(dict)
    
    # [新增] 權重改變的訊號
    weights_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent# [新增] 儲存父視窗以便讀寫設定
        self.setFixedWidth(360)

        self.setObjectName("InspectorPanel")
        
        # 專屬的現代化暗色系樣式
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # 建立分頁元件
        self.tabs = QTabWidget()

        self.tabs.setObjectName("InspectorTabs")

        self.layout.addWidget(self.tabs)

        # --- 分頁 1: 搜尋控制 ---
        self.tab_search = QWidget()
        self._setup_search_tab()
        self.tabs.addTab(self.tab_search, "🔎 搜尋")

        # ==========================================
        # [新增] 分頁 1.5: CLIP 控制
        # ==========================================
        self.tab_clip = QWidget()
        self._setup_clip_tab()
        self.tabs.addTab(self.tab_clip, "👁️ CLIP")

        # --- 分頁 2: OCR 細節 ---
        self.tab_ocr = QWidget()
        self._setup_ocr_tab()
        self.tabs.addTab(self.tab_ocr, "🔤 OCR")

        # --- 分頁 3: 圖片資訊 ---
        self.tab_info = QWidget()
        self._setup_info_tab()
        self.tabs.addTab(self.tab_info, "ℹ️ 資訊")

        self.hide() # 預設隱藏，等待按鈕觸發

    def _setup_search_tab(self):
        tab_layout = QVBoxLayout(self.tab_search)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("InspectorScrollArea")
        
        container = QWidget()
        container.setObjectName("SearchTabContainer")
        
        self.search_main_layout = QVBoxLayout(container)
        self.search_main_layout.setContentsMargins(0, 0, 0, 0)
        self.search_main_layout.setSpacing(0)
        self.search_main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- 區塊 1: 🔍 檢索過濾 (FILTER) ---
        self.sec_filter = CollapsibleSection("檢索過濾")

        trans = self.main_window.config.translator
        
        self.sec_filter.addWidget(QLabel(trans.t("search_filter", "lbl_search_scope", "搜尋範圍 (Search Scope):")))
        self.combo_search_scope = QComboBox()
        self.combo_search_scope.addItems([
            trans.t("search_filter", "scope_local", "📂 目前資料夾 (Local)"),
            trans.t("search_filter", "scope_global", "🌍 全域搜尋 (Global)")
        ])
        self.combo_search_scope.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_search_scope.setFixedHeight(38)
        self.sec_filter.addWidget(self.combo_search_scope)
        
        line_scope = QFrame()
        line_scope.setFrameShape(QFrame.Shape.HLine)
        line_scope.setStyleSheet("border-top: 1px solid #3c3c3c; margin: 5px 0;")
        self.sec_filter.addWidget(line_scope)
        
        self.btn_time_range = QPushButton("📅 全部時間 (All Time)")
        self.btn_time_range.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_time_range.setCheckable(True)
        self.btn_time_range.setObjectName("TimeRangeBtn")
        self.btn_time_range.clicked.connect(self.toggle_calendar)
        self.sec_filter.addWidget(self.btn_time_range)

        self.calendar_widget = RangeCalendarWidget()
        self.calendar_widget.hide()
        self.calendar_widget.apply_requested.connect(self.on_calendar_apply)
        self.calendar_widget.search_requested.connect(self.on_calendar_search)
        self.calendar_widget.cleared.connect(self.on_calendar_cleared)
        self.calendar_widget.selection_started.connect(self.on_calendar_picking)
        self.sec_filter.addWidget(self.calendar_widget)

        self.lbl_aspect_title = QLabel("視覺規格 (Visual Specs):")
        self.lbl_aspect_title.setObjectName("FilterTitle")
        self.sec_filter.addWidget(self.lbl_aspect_title)
        
        self.combo_aspect = QComboBox()
        self.combo_aspect.addItems(["不限比例", "橫圖 (Landscape)", "直圖 (Portrait)", "正方形 (Square)"])
        
        if not hasattr(self, 'aspect_changed'): self.aspect_changed = pyqtSignal()
        self.combo_aspect.currentIndexChanged.connect(self.on_aspect_changed)
        self.sec_filter.addWidget(self.combo_aspect)
        self.search_main_layout.addWidget(self.sec_filter)

        # --- 區塊 2: ⚙️ 顯示設定 (DISPLAY) ---
        self.sec_display = CollapsibleSection("顯示設定")
        self.sec_display.addWidget(QLabel("顯示數量限制 (Limit):"))
        self.combo_limit_panel = QComboBox()
        self.combo_limit_panel.addItems(["20", "50", "100", "All"])

        self.combo_limit_panel.currentIndexChanged.connect(self.on_limit_changed)

        self.sec_display.addWidget(self.combo_limit_panel)

        self.sec_display.addWidget(QLabel("Gallery 排序方式 (Sort By):"))
        sort_layout = QHBoxLayout()
        sort_layout.setContentsMargins(0, 0, 0, 0)
        sort_layout.setSpacing(8)
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["搜尋相關度", "日期", "名稱", "類型", "大小"])
        self.combo_sort.currentIndexChanged.connect(lambda: self.sort_changed.emit())
        sort_layout.addWidget(self.combo_sort, stretch=1)

        self.btn_sort_order = QPushButton("↓")
        self.btn_sort_order.setFixedSize(32, 32)
        self.btn_sort_order.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sort_order.setObjectName("SortOrderBtn")
        self.btn_sort_order.clicked.connect(self.toggle_sort_order)
        sort_layout.addWidget(self.btn_sort_order)
        
        self.sec_display.addLayout(sort_layout)
        self.search_main_layout.addWidget(self.sec_display)

        # --- 區塊 3: 🧪 進階功能 (ADVANCED) ---
        self.sec_advanced = CollapsibleSection("相關度權重控制")
        
        mode_layout = QHBoxLayout()
        self.combo_calc_mode = QComboBox()
        self.combo_calc_mode.addItems(["乘法模式 (Multiplication)", "加法模式 (Addition)"])
        self.combo_calc_mode.currentIndexChanged.connect(self.on_calc_mode_changed)
        mode_layout.addWidget(self.combo_calc_mode)
        self.sec_advanced.addLayout(mode_layout)

        self.lbl_formula = QLabel()
        self.lbl_formula.setObjectName("FormulaLabel")
        self.sec_advanced.addWidget(self.lbl_formula)

        self.lbl_clip_weight = QLabel()
        self.sec_advanced.addWidget(self.lbl_clip_weight)
        self.slider_clip = QSlider(Qt.Orientation.Horizontal)
        self.slider_clip.setRange(0, 100)
        self.slider_clip.valueChanged.connect(self.update_weight_labels)
        self.slider_clip.sliderReleased.connect(self.on_weight_slider_released)
        self.sec_advanced.addWidget(self.slider_clip)

        self.lbl_ocr_weight = QLabel()
        self.sec_advanced.addWidget(self.lbl_ocr_weight)
        self.slider_ocr = QSlider(Qt.Orientation.Horizontal)
        self.slider_ocr.setRange(0, 100)
        self.slider_ocr.valueChanged.connect(self.update_weight_labels)
        self.slider_ocr.sliderReleased.connect(self.on_weight_slider_released)
        self.sec_advanced.addWidget(self.slider_ocr)

        self.lbl_name_weight = QLabel()
        self.sec_advanced.addWidget(self.lbl_name_weight)
        self.slider_name = QSlider(Qt.Orientation.Horizontal)
        self.slider_name.setRange(0, 100)
        self.slider_name.valueChanged.connect(self.update_weight_labels)
        self.slider_name.sliderReleased.connect(self.on_weight_slider_released)
        self.sec_advanced.addWidget(self.slider_name)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("border-top: 1px solid #3c3c3c; margin: 10px 0;")
        self.sec_advanced.addWidget(line)

        self.sec_advanced.addWidget(QLabel("結果過濾門檻 (Threshold):"))
        self.combo_threshold_mode = QComboBox()
        self.combo_threshold_mode.addItems(["自動 (最高分的一半)", "手動 (自訂最低分)"])
        self.combo_threshold_mode.currentIndexChanged.connect(self.on_threshold_mode_changed)
        self.sec_advanced.addWidget(self.combo_threshold_mode)

        self.lbl_threshold_val = QLabel()
        self.sec_advanced.addWidget(self.lbl_threshold_val)
        self.slider_threshold = QSlider(Qt.Orientation.Horizontal)
        self.slider_threshold.setRange(1, 50) 
        self.slider_threshold.valueChanged.connect(self.update_weight_labels)
        self.slider_threshold.sliderReleased.connect(self.on_weight_slider_released)
        self.sec_advanced.addWidget(self.slider_threshold)
        
        btn_reset = QPushButton("🔄 重置為預設權重")
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.setObjectName("ResetWeightBtn")
        btn_reset.clicked.connect(self.reset_weights_to_default)
        self.sec_advanced.addWidget(btn_reset)
        
        self.search_main_layout.addWidget(self.sec_advanced)
        self.sec_advanced.set_expanded(True) # 預設展開

        QTimer.singleShot(0, self.load_weight_settings)

        self.search_main_layout.addStretch(1)
        scroll_area.setWidget(container)
        tab_layout.addWidget(scroll_area)

        self.btn_clear_all = QPushButton("🗑️ 清除所有過濾條件")
        self.btn_clear_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_all.setObjectName("ClearFilterBtn")
        self.btn_clear_all.clicked.connect(self.clear_all_filters)
        self.btn_clear_all.hide()
        tab_layout.addWidget(self.btn_clear_all)

    def toggle_sort_order(self):
        """切換排序方向 (正序 ↑ / 倒序 ↓)"""
        if self.btn_sort_order.text() == "↓":
            self.btn_sort_order.setText("↑")
            self.btn_sort_order.setToolTip("目前為：正序 (由小到大 / 舊到新)")
        else:
            self.btn_sort_order.setText("↓")
            self.btn_sort_order.setToolTip("目前為：倒序 (由大到小 / 新到舊)")
            
        
        self.sort_changed.emit()

    # ==========================
    # [優化] 抽離重複的按鈕樣式
    # ==========================
    def _create_construction_button(self, text):
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setObjectName("WipButton") #  套用修復的 QSS
        return btn

    def on_vector_box_changed(self):
        # 使用新的 get_paths() 方法取得資料
        pos_paths = self.pos_box.get_paths()
        neg_paths = self.neg_box.get_paths()
        total = len(pos_paths) + len(neg_paths)

        if total == 1 and len(pos_paths) == 1:
            # 只有一張正向圖片 -> 瞬間自動觸發以圖搜圖！
            self.btn_vector_search.hide()
            self.main_window.start_image_search(pos_paths[0])
        elif total > 0:
            # 多張圖片 -> 顯示「組合搜尋」按鈕讓使用者手動確認
            self.btn_vector_search.show()
            self.btn_vector_search.setText(f"組合搜尋 (正:{len(pos_paths)} 負:{len(neg_paths)})")
        else:
            self.btn_vector_search.hide()

    def _setup_clip_tab(self):
        # FeatureBucketWidget 仍留在 Blur-main.py，延遲引入避免循環
        from __main__ import FeatureBucketWidget

        layout = QVBoxLayout(self.tab_clip)
        layout.setSpacing(15); layout.setContentsMargins(15, 20, 15, 20); layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        lbl_desc = QLabel("拖曳圖片或文字到下方方塊，\n進行多模態語義特徵的組合或排除。")
        
        # 🌟 重構魔法：核發身分證，樣式交給 QSS
        lbl_desc.setObjectName("ClipTabDesc") 
        layout.addWidget(lbl_desc)

        # 🌟 徹底拔除！不再傳入寫死的色碼，因為 QSS 已經會看 polarity 自動變色了
        self.pos_box = FeatureBucketWidget("➕ 正向特徵 (Positive)", is_positive=True, main_window=self.main_window) 
        self.pos_box.setFixedHeight(150)
        self.neg_box = FeatureBucketWidget("➖ 負向排除 (Negative)", is_positive=False, main_window=self.main_window)
        self.neg_box.setFixedHeight(150)
        
        layout.addWidget(self.pos_box); layout.addWidget(self.neg_box)

        self.btn_vector_search = QPushButton("🚀 組合搜尋")
        self.btn_vector_search.setProperty("cssClass", "ActionBtn")
        self.btn_vector_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vector_search.hide()
        self.btn_vector_search.clicked.connect(self.trigger_multi_vector_search)
        layout.addWidget(self.btn_vector_search)

        #  文字拖拽時自動清空主搜尋框
        self.pos_box.text_dropped.connect(self.main_window.input.clear)
        self.neg_box.text_dropped.connect(self.main_window.input.clear)

        self.pos_box.files_changed.connect(self.on_vector_box_changed)
        self.neg_box.files_changed.connect(self.on_vector_box_changed)
        layout.addStretch(1)

    def on_vector_box_changed(self):
        pos_features = self.pos_box.get_features()
        neg_features = self.neg_box.get_features()
        total = len(pos_features) + len(neg_features)

        # 只有一張圖片時才自動搜，文字則保留手動確認
        if total == 1 and len(pos_features) == 1 and pos_features[0].type == 'image':
            self.btn_vector_search.hide()
            self.main_window.start_image_search(pos_features[0].data)
        elif total > 0:
            self.btn_vector_search.show()
            self.btn_vector_search.setText(f"🚀 組合搜尋 (正:{len(pos_features)} 負:{len(neg_features)})")
        else:
            self.btn_vector_search.hide()

    def trigger_multi_vector_search(self):
        pos_features = self.pos_box.get_features()
        neg_features = self.neg_box.get_features()
        self.main_window.start_multi_vector_search(pos_features, neg_features)

    def _setup_ocr_tab(self):
        # 修正：原代碼誤寫為 self.tab_clip，現已改回 self.tab_ocr
        layout = QVBoxLayout(self.tab_ocr) 
        layout.setSpacing(15)
        layout.setContentsMargins(20, 25, 20, 20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 修正：使用正確的按鈕變數名稱
        self.btn_test_ocr = self._create_construction_button("🚧 施工中：進階 OCR 屬性分析")
        layout.addWidget(self.btn_test_ocr)

        layout.addStretch(1)

    def _setup_info_tab(self):
        layout = QVBoxLayout(self.tab_info)
        layout.setSpacing(15); layout.setContentsMargins(20, 25, 20, 20)

        # 頂部圖片預覽
        self.preview_lbl = QLabel("尚未選取圖片")
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setMinimumHeight(180)
        self.preview_lbl.setObjectName("PreviewImage")
        layout.addWidget(self.preview_lbl)

        # 檔案名稱
        self.filename_lbl = QLabel("尚未選取檔案")
        self.filename_lbl.setWordWrap(True)
        self.filename_lbl.setStyleSheet("font-size: 15px; font-weight: bold; background: transparent;")
        layout.addWidget(self.filename_lbl)

        # 開啟資料夾按鈕
        self.btn_open_folder = QPushButton("📂 開啟檔案位置")
        self.btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_folder.setProperty("cssClass", "ActionBtn")
        layout.addWidget(self.btn_open_folder)

        #  [修正 1] 新增一個變數來記住現在點到哪張圖，並只在初始化時綁定一次訊號！
        self.current_info_path = ""
        self.btn_open_folder.clicked.connect(self._on_open_folder_clicked)

        # 詳細屬性網格
        self.grid = QGridLayout()
        self.grid.setVerticalSpacing(10); self.grid.setHorizontalSpacing(10)
        self.fields = {}
        properties = ["類型", "大小", "修改日期", "AI 相關度"]
        
        for i, key in enumerate(properties):
            lbl_key = QLabel(key)
            lbl_key.setObjectName("InfoLabelKey")
            lbl_value = QLabel("-")
            lbl_value.setObjectName("InfoLabelValue")
            lbl_value.setWordWrap(True)
            self.grid.addWidget(lbl_key, i, 0, Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(lbl_value, i, 1, Qt.AlignmentFlag.AlignTop)
            self.fields[key] = lbl_value

        layout.addLayout(self.grid)
        layout.addStretch(1)

    def update_info(self, item):
        """當主畫面點擊圖片時，呼叫此函式更新第三分頁的資料"""
        self.filename_lbl.setText(item.filename)
        
        # 智慧縮放預覽圖
        reader = QImageReader(item.path)
        reader.setAutoTransform(True)
        img_size = reader.size()
        if img_size.isValid():
            scaled_size = img_size.scaled(QSize(260, 180), Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(scaled_size)
            img = reader.read()
            if not img.isNull():
                self.preview_lbl.setPixmap(QPixmap.fromImage(img))
                self.preview_lbl.setStyleSheet("background-color: transparent; border: none;")

        #  [修正 2] 拔掉原本的 disconnect() 和 lambda，改為單純更新路徑變數
        self.current_info_path = item.path

        # 更新文字屬性
        try:
            file_stat = os.stat(item.path)
            ext = os.path.splitext(item.filename)[1].upper()
            self.fields["類型"].setText(f"{ext} 檔案" if ext else "未知")
            self.fields["大小"].setText(f"{file_stat.st_size / (1024 * 1024):.2f} MB")
            dt = datetime.fromtimestamp(item.mtime)
            self.fields["修改日期"].setText(dt.strftime("%Y/%m/%d %H:%M"))
            self.fields["AI 相關度"].setText(f"{item.score:.4f}" if item.score > 0 else "N/A")
        except: pass
    
    #  [新增] 專門處理按鈕點擊的函式
    def _on_open_folder_clicked(self):
        if self.current_info_path:
            self.open_in_explorer(self.current_info_path)

    @staticmethod
    def open_in_explorer(path):
        if os.name == 'nt':
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
    
    def toggle_calendar(self):
        """絕對由 📅 時間按鈕控制日曆的展開與收合"""
        is_checked = self.btn_time_range.isChecked()
        self.calendar_widget.setVisible(is_checked)
        
        if is_checked and "全部時間" in self.btn_time_range.text():
            self.btn_time_range.setText("📅 自訂區間 (等待操作)...")
    
    def on_calendar_picking(self):
        """點了第一下，只更新日曆內的文字，不干擾主按鈕"""
        pass # UI 回饋已經由 RangeCalendarWidget 的 lbl_status 負責了

    def on_date_range_selected(self, start_date, end_date):
        """選取完畢，更新按鈕文字 (不自動收合)"""
        if start_date == end_date:
             date_str = f"📅 {start_date.strftime('%Y/%m/%d')}"
        else:
             date_str = f"📅 {start_date.strftime('%Y/%m/%d')} - {end_date.strftime('%Y/%m/%d')}"
        self.btn_time_range.setText(date_str)

    def on_calendar_cleared(self):
        """使用者按下清除日期"""
        self._has_time_filter = False  #  [修復] 使用獨立狀態變數
        self.btn_time_range.setText("📅 全部時間 (All Time)")
        self.time_filter_cleared.emit()

        self.check_filters_active()

    def on_calendar_apply(self, start_date, end_date):
        """點擊 [套用結果]：轉換為 Timestamp 並發送訊號"""
        self._has_time_filter = True   #  [修復] 標記時間過濾已啟用
        date_str = f"📅 {start_date.strftime('%Y/%m/%d')} - {end_date.strftime('%Y/%m/%d')}"
        self.btn_time_range.setText(date_str)
        
        start_ts = datetime.combine(start_date, dt_time.min).timestamp()
        end_ts = datetime.combine(end_date, dt_time.max).timestamp()
        
        self.time_filter_applied.emit(start_ts, end_ts)

        self.check_filters_active()

    def on_calendar_search(self, start_date, end_date):
        """點擊 [直接搜尋]：轉換為 Timestamp 並發送訊號 (狀態交由 MainWindow 判定)"""
        self._has_time_filter = True   #  [修復] 標記時間過濾已啟用
        date_str = f"📅 {start_date.strftime('%Y/%m/%d')} - {end_date.strftime('%Y/%m/%d')}"
        self.btn_time_range.setText(date_str)
        
        start_ts = datetime.combine(start_date, dt_time.min).timestamp()
        end_ts = datetime.combine(end_date, dt_time.max).timestamp()
        
        # 發送訊號讓 MainWindow 去要資料並驗證
        self.time_search_requested.emit(start_ts, end_ts)
        
        self.check_filters_active()

    # ==========================================
    #  神經中樞：過濾狀態檢查與清除
    # ==========================================
    def on_aspect_changed(self):
        """長寬比改變時，觸發狀態檢查，並通知 MainWindow 洗牌"""
        self.check_filters_active()
        self.aspect_changed.emit()

    def check_filters_active(self):
        """檢查是否有任何過濾器正在運作，並更新 UI 狀態 (包含分頁計數徽章)"""
        
        #  [終極修復] 完全拔除中文字串依賴，改用隱藏屬性與 Index 判斷！
        is_time_filtered = getattr(self, '_has_time_filter', False)
        is_aspect_filtered = (self.combo_aspect.currentIndex() != 0) # 只要不是 0 (不限比例)，就是啟動過濾
        
        #  計算啟用的過濾條件數量
        active_count = 0
        if is_time_filtered: active_count += 1
        if is_aspect_filtered: active_count += 1
        
        any_active = (active_count > 0)

        # 1. 層級三：屬性控制 (交由 QSS 處理顏色)
        time_state = "true" if is_time_filtered else "false"
        aspect_state = "true" if is_aspect_filtered else "false"
        
        # (順手修復一個潛在的報錯 BUG：原本程式碼中沒有 lbl_time_title 這個物件，應該是 btn_time_range)
        self.btn_time_range.setProperty("active", time_state)
        self.lbl_aspect_title.setProperty("active", aspect_state)
        
        self.btn_time_range.style().unpolish(self.btn_time_range)
        self.btn_time_range.style().polish(self.btn_time_range)
        self.lbl_aspect_title.style().unpolish(self.lbl_aspect_title)
        self.lbl_aspect_title.style().polish(self.lbl_aspect_title)

        # 2. 層級二：檢索過濾區塊底線
        self.sec_filter.set_status_active(any_active)

        #  3. 層級一：分頁標籤數字計數徽章 (Badge Count)
        if active_count > 0:
            self.tabs.setTabText(0, f"🔎 搜尋 ({active_count})")
        else:
            self.tabs.setTabText(0, "🔎 搜尋")

        # 4. 底部：顯示/隱藏置底的清除按鈕
        self.btn_clear_all.setVisible(any_active)

    def clear_all_filters(self):
        """一鍵清除所有過濾狀態"""
        # 1. 靜默重置長寬比 (不觸發訊號)
        self.combo_aspect.blockSignals(True)
        self.combo_aspect.setCurrentIndex(0) #  [修復] 不再依賴文字 "不限比例"，直接歸零 Index
        self.combo_aspect.blockSignals(False)
        
        # 2. 重置日曆與時間狀態
        self._has_time_filter = False        #  [修復] 同步歸零隱藏狀態
        self.btn_time_range.setText("📅 全部時間 (All Time)")
        self.calendar_widget.clear_selection()
        
        # 3. 發送訊號給 MainWindow 執行還原
        self.time_filter_cleared.emit()
        
        # 4. 自我更新 UI 底線狀態
        self.check_filters_active()

    # ==========================================
    #  相關度權重控制邏輯 (放在 InspectorPanel 底部)
    # ==========================================
    def load_weight_settings(self):
        ui_state = self.main_window.config.get("ui_state", {})

        limit_val = str(ui_state.get("search_limit", "50"))
        index = self.combo_limit_panel.findText(limit_val)
        if index >= 0:
            self.combo_limit_panel.blockSignals(True) # 避免啟動時觸發不必要的搜尋
            self.combo_limit_panel.setCurrentIndex(index)
            self.combo_limit_panel.blockSignals(False)

        mode = ui_state.get("search_calc_mode", "multiply")
        self.combo_calc_mode.setCurrentIndex(0 if mode == "multiply" else 1)

        mode = ui_state.get("search_calc_mode", "multiply")
        self.combo_calc_mode.setCurrentIndex(0 if mode == "multiply" else 1)
        
        self.slider_clip.setValue(ui_state.get("search_weight_clip", 100))
        self.slider_ocr.setValue(ui_state.get("search_weight_ocr", 100))
        self.slider_name.setValue(ui_state.get("search_weight_name", 40))
        
        thresh_mode = ui_state.get("search_thresh_mode", "auto")
        self.combo_threshold_mode.setCurrentIndex(0 if thresh_mode == "auto" else 1)
        self.slider_threshold.setValue(int(ui_state.get("search_thresh_val", 15)))
        
        self.update_weight_labels()
        self.on_calc_mode_changed(self.combo_calc_mode.currentIndex(), save=False)
        self.on_threshold_mode_changed(self.combo_threshold_mode.currentIndex(), save=False)

    def on_limit_changed(self):
        """當使用者改變顯示數量時，儲存設定並觸發即時重新搜尋"""
        ui_state = self.main_window.config.get("ui_state", {})
        
        limit_text = self.combo_limit_panel.currentText()
        if limit_text == "All":
            ui_state["search_limit"] = "All"
        else:
            ui_state["search_limit"] = int(limit_text)
            
        self.main_window.config.set("ui_state", ui_state)
        
        # 觸發重新搜尋 (因為底層有文字特徵快取，這會是 0 毫秒瞬間更新)
        self.weights_changed.emit(self.get_weight_config())

    def reset_weights_to_default(self):
        self.combo_calc_mode.setCurrentIndex(0)
        self.slider_clip.setValue(100)
        self.slider_ocr.setValue(100)
        self.slider_name.setValue(40)
        self.combo_threshold_mode.setCurrentIndex(0)
        self.slider_threshold.setValue(15)
        self.on_weight_slider_released()

    def on_calc_mode_changed(self, index, save=True):
        is_add = (index == 1)
        if is_add:
            self.slider_clip.setEnabled(False)
        else:
            self.slider_clip.setEnabled(True)
            
        #  把公式文字的更新移交給 update_weight_labels 統一處理
        self.update_weight_labels()
        if save: self.on_weight_slider_released()

    def on_threshold_mode_changed(self, index, save=True):
        is_manual = (index == 1)
        self.lbl_threshold_val.setVisible(is_manual)
        self.slider_threshold.setVisible(is_manual)
        if save: self.on_weight_slider_released()

    def update_weight_labels(self):
        is_add = (self.combo_calc_mode.currentIndex() == 1)
        
        # 取得實際滑桿的浮點數值
        clip_v = self.slider_clip.value() / 100.0
        ocr_v = self.slider_ocr.value() / 100.0
        name_v = self.slider_name.value() / 100.0
        
        # 加法模式的實際加分 (0.0 ~ 0.5)
        ocr_add = self.slider_ocr.value() / 200.0
        name_add = self.slider_name.value() / 200.0

        if is_add:
            self.lbl_clip_weight.setText("視覺權重 (CLIP 固定為原始分數)")
            self.lbl_ocr_weight.setText(f"文字加分 (OCR Bonus): +{ocr_add:.2f}")
            self.lbl_name_weight.setText(f"名稱加分 (Filename Bonus): +{name_add:.2f}")
            # 移除「公式:」並顯示動態數字
            self.lbl_formula.setText(f"CLIP分數 + (OCR命中? +{ocr_add:.2f}) + (檔名命中? +{name_add:.2f})")
        else:
            self.lbl_clip_weight.setText(f"視覺權重 (CLIP Weight): x{clip_v:.2f}")
            self.lbl_ocr_weight.setText(f"文字權重 (OCR Bonus): x{ocr_v:.2f}")
            self.lbl_name_weight.setText(f"名稱權重 (Filename Bonus): x{name_v:.2f}")
            # 計算基準乘法分數並顯示
            ocr_calc = 0.5 * ocr_v
            name_calc = 0.5 * name_v
            self.lbl_formula.setText(f"(CLIP × {clip_v:.2f}) + (OCR命中? {ocr_calc:.2f}) + (檔名命中? {name_calc:.2f})")
            
        self.lbl_threshold_val.setText(f"手動門檻值: {self.slider_threshold.value() / 100:.2f}")

    def on_weight_slider_released(self):
        """放開滑桿時，儲存設定並觸發 MainWindow 重新搜尋"""
        ui_state = self.main_window.config.get("ui_state", {})
        ui_state["search_calc_mode"] = "add" if self.combo_calc_mode.currentIndex() == 1 else "multiply"
        ui_state["search_weight_clip"] = self.slider_clip.value()
        ui_state["search_weight_ocr"] = self.slider_ocr.value()
        ui_state["search_weight_name"] = self.slider_name.value()
        ui_state["search_thresh_mode"] = "manual" if self.combo_threshold_mode.currentIndex() == 1 else "auto"
        ui_state["search_thresh_val"] = self.slider_threshold.value()
        self.main_window.config.set("ui_state", ui_state)
        self.weights_changed.emit(self.get_weight_config())

    def get_weight_config(self):
        """產生提供給 AI 引擎的參數包"""
        return {
            "mode": "add" if self.combo_calc_mode.currentIndex() == 1 else "multiply",
            "clip_w": self.slider_clip.value() / 100.0,
            "ocr_w": self.slider_ocr.value() / 100.0,
            "name_w": self.slider_name.value() / 100.0,
            "thresh_mode": "manual" if self.combo_threshold_mode.currentIndex() == 1 else "auto",
            "thresh_val": self.slider_threshold.value() / 100.0
        }
