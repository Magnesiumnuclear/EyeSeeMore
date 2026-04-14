"""
SearchOrchestrator  –  SearchWorker 生命週期管理器
====================================================
從 MainWindow 抽離的職責：
  • SearchWorker 的建立、訊號連接、啟動
  • 執行中 Worker 的安全退役（斷訊號 + 收容所防 C++ 幽靈物件）
  • fetch_k / target_folder 參數的統一解析
  • 將結果訊號向上中繼給 MainWindow

使用方式：
    orchestrator = SearchOrchestrator(SearchWorker, parent=main_window)
    orchestrator.results_ready.connect(main_window.set_base_results)
    orchestrator.search_finished.connect(main_window.on_finished)
    # 引擎載入後注入
    orchestrator.engine = self.engine
    # 開始搜尋
    orchestrator.submit(query, search_mode="text", ...)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional, Type

from PyQt6.QtCore import QObject, pyqtSignal

if TYPE_CHECKING:
    pass  # 避免循環 import


class SearchOrchestrator(QObject):
    """封裝 SearchWorker 的完整生命週期。"""

    # 向 MainWindow 中繼的訊號
    results_ready = pyqtSignal(list)       # batch_ready → results_ready
    search_finished = pyqtSignal(float, int)  # finished_search → search_finished

    def __init__(self, worker_class: Type, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._WorkerClass = worker_class
        self._current_worker = None
        self._retained: list = []      # 收容所：防止 C++ 幽靈物件
        self.engine = None             # 延遲注入

    # ------------------------------------------------------------------
    #  公開介面
    # ------------------------------------------------------------------
    def submit(
        self,
        query,
        *,
        search_mode: str = "text",
        use_ocr: bool = False,
        weight_config=None,
        folder_path=None,
        fetch_k: int = 2000,
    ) -> None:
        """退役舊 Worker 並建立新 Worker 開始搜尋。"""
        if self.engine is None:
            return

        self._retire_current()

        worker = self._WorkerClass(
            self.engine,
            query,
            fetch_k,
            search_mode=search_mode,
            use_ocr=use_ocr,
            weight_config=weight_config,
            folder_path=folder_path,
        )
        worker.batch_ready.connect(self.results_ready)
        worker.finished_search.connect(self.search_finished)
        worker.finished.connect(self._make_cleanup(worker))
        worker.finished.connect(worker.deleteLater)

        self._current_worker = worker
        worker.start()

    @staticmethod
    def resolve_search_params(inspector_panel, current_folder_path) -> tuple[int, Optional[str]]:
        """從 InspectorPanel 解析 fetch_k 與 target_folder。

        Returns
        -------
        (fetch_k, target_folder)
        """
        limit = inspector_panel.combo_limit_panel.currentText()
        fetch_k = 100000 if limit == "All" else 2000

        target_folder = None
        is_local_mode = (inspector_panel.combo_search_scope.currentIndex() == 0)
        if is_local_mode and current_folder_path != "ALL":
            target_folder = current_folder_path

        return fetch_k, target_folder

    # ------------------------------------------------------------------
    #  私有輔助
    # ------------------------------------------------------------------
    def _retire_current(self) -> None:
        """斷開舊 Worker 的訊號；若它還在執行，送入收容所等自然消滅。"""
        worker = self._current_worker
        if worker is None:
            return
        try:
            worker.batch_ready.disconnect()
            worker.finished_search.disconnect()
            if worker.isRunning():
                self._retained.append(worker)
        except (RuntimeError, TypeError):
            # C++ 底層已被 deleteLater 刪除，安全忽略
            pass
        self._current_worker = None

    def _make_cleanup(self, worker) -> Callable:
        """回傳一個 closure，Worker 完成後從收容所移除自身。"""
        def _cleanup():
            try:
                self._retained.remove(worker)
            except ValueError:
                pass
        return _cleanup
