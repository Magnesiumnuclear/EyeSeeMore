# ==========================================
#  navigation_manager.py
#  EyeSeeMore - 搜尋歷史堆疊與路徑導航管理器
#  從 MainWindow 中提取的前進/後退邏輯與狀態快照管理。
# ==========================================


class NavigationManager:
    """
    管理瀏覽器風格的前進/後退導航堆疊。

    【設計原則】
    此類別只負責「堆疊資料結構」的操作與狀態流轉，
    不直接操作任何 UI 元件或觸發業務邏輯。
    所有 UI 副作用透過兩個回呼函式執行：
      - state_snapshot_fn()  : 回傳當前頁面快照 dict
      - apply_state_fn(state): 還原快照並觸發對應的搜尋/載入
    按鈕啟用狀態透過 update_buttons_fn(can_back, can_forward) 通知。

    【快照格式 (由 MainWindow 定義)】
    {
        "query": str,
        "folder_path": str,
        "breadcrumb": str,
        "scroll_pos": int,
        "image_path": str | None,
    }
    """

    def __init__(self, *, state_snapshot_fn, apply_state_fn, update_buttons_fn):
        self._back_stack = []
        self._forward_stack = []
        self._is_navigating = False
        self.pending_scroll_pos = None

        # 回呼函式 (由 MainWindow 注入)
        self._snapshot = state_snapshot_fn
        self._apply = apply_state_fn
        self._update_buttons = update_buttons_fn

    # ------------------------------------------------------------------
    #  公開屬性
    # ------------------------------------------------------------------
    @property
    def is_navigating(self):
        return self._is_navigating

    # ------------------------------------------------------------------
    #  核心操作
    # ------------------------------------------------------------------
    def push(self):
        """
        儲存當前狀態並清空前進棧。
        應在觸發「新的」搜尋或資料夾切換前呼叫。
        在 navigate_back/forward 期間呼叫會被自動忽略。
        """
        if self._is_navigating:
            return
        state = self._snapshot()
        self._back_stack.append(state)
        self._forward_stack.clear()
        self._update_buttons(self.can_go_back, self.can_go_forward)

    def go_back(self):
        """後退一步：將當前狀態壓入前進棧，從後退棧彈出並套用。"""
        if not self._back_stack:
            return
        self._is_navigating = True
        self._forward_stack.append(self._snapshot())
        target = self._back_stack.pop()
        self._apply_target(target)
        self._is_navigating = False

    def go_forward(self):
        """前進一步：將當前狀態壓入後退棧，從前進棧彈出並套用。"""
        if not self._forward_stack:
            return
        self._is_navigating = True
        self._back_stack.append(self._snapshot())
        target = self._forward_stack.pop()
        self._apply_target(target)
        self._is_navigating = False

    # ------------------------------------------------------------------
    #  查詢
    # ------------------------------------------------------------------
    @property
    def can_go_back(self):
        return len(self._back_stack) > 0

    @property
    def can_go_forward(self):
        return len(self._forward_stack) > 0

    # ------------------------------------------------------------------
    #  內部輔助
    # ------------------------------------------------------------------
    def _apply_target(self, state):
        self.pending_scroll_pos = state.get("scroll_pos")
        self._apply(state)
        self._update_buttons(self.can_go_back, self.can_go_forward)
