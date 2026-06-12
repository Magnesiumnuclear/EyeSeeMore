import os
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QImage

# [Perf Phase 3-G] 不在頂層 import indexer：
# 它會連帶載入 cv2 / onnxruntime / onnx_ocr（shapely、pyclipper）等重模組，
# 而本模組在 Blur-main.py 頂層被 import，會直接拖慢主視窗啟動。
# IndexerService 改為 IndexerWorker.run()（背景執行緒）內 lazy 建立。
from export_clip_onnx import export_to_onnx


class WorkerSignals(QObject):
    result = pyqtSignal(str, QPixmap, bool) #加入一個布林值 is_final，讓系統知道這是不是最終的高清圖

class PreviewSignals(QObject):
    #  關鍵修復：將跨執行緒的傳遞物件從 QPixmap 換成絕對安全的 QImage
    result = pyqtSignal(str, QImage, list, int, int, str, bool)


class IndexerWorker(QThread):
    """
    背景索引工作者
    階段 1: 掃描檔案 (Scan) -> 回報 scan_finished
    階段 2: 若有新檔案，執行 AI 處理 (Process) -> 回報 progress -> finished
    """
    status_update = pyqtSignal(str)
    progress_update = pyqtSignal(int, int)
    scan_finished = pyqtSignal(int, int)
    all_finished = pyqtSignal()
    # 純粹的真實剩餘秒數，由主執行緒的 PID timer 轉換成假時間顯示
    # -1.0 = 暖機中（樣本不足），0.0 = 完成
    eta_updated = pyqtSignal(float)

    # [修改 1] 加入 main_window 參數，以取得主程式的 AI 模型
    def __init__(self, config, main_window):
        super().__init__()
        self.config = config
        self.main_window = main_window
        # IndexerService 延後到 run()（背景執行緒）才建立，
        # 避免 import indexer 的重模組成本阻塞主視窗啟動
        self.service = None
        #直接傳遞包含 use_ocr 屬性的完整字典列表！
        self.folders = config.get("source_folders")

        # ── 暫停 / 取消控制 ──────────────────────────────────────
        # _resume_event.set()   = 執行中（預設）
        # _resume_event.clear() = 暫停（callback 中阻塞等候）
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._paused    = False   # UI 狀態旗標（供 MainWindow 讀取）
        self._cancelled = False   # 取消旗標

    def run(self):
        # 每次啟動時重置控制旗標
        self._cancelled = False
        self._paused    = False
        self._resume_event.set()

        # Lazy 建立 IndexerService（首次掃描時，於本背景執行緒內付 import 成本）
        if self.service is None:
            from indexer import IndexerService
            self.service = IndexerService(
                db_path=self.config.db_path,
                model_name=self.config.get("model_name"),
                pretrained_name=self.config.get("pretrained"),
                use_gpu_ocr=self.config.get("use_gpu_ocr"),
                perf_config=self.config.get("performance", {})
            )

        # --- 階段 1: 智慧掃描 ---
        self.status_update.emit("Scanning for file changes...")
        try:
            # [修正] 接收新的回傳值
            files_full, files_emb_only, files_ocr_only, deleted_count, folder_ocr_map = self.service.scan_for_new_files(self.folders)
            self.scan_finished.emit(len(files_full) + len(files_emb_only) + len(files_ocr_only), deleted_count)
        except Exception as e:
            print(f"Scan Error: {e}"); self.status_update.emit("Scan failed."); return

        if not files_full and not files_emb_only and not files_ocr_only:
            self.status_update.emit("No new images found."); self.all_finished.emit(); return

        total_tasks = len(files_full) + len(files_emb_only) + len(files_ocr_only)
        self.status_update.emit(f"Indexing {total_tasks} images...")

        # [Refactor Phase 3-A] 移除 WAIT_LOOP
        # 改為檢查模型可用性，若模式未就緒則由 indexer.py 執行 Lazy Load
        # 這樣 IndexerWorker 不再被阻塞，可立刻啟動掃描與索引

        # [Refactor Phase 2-B] 改透過 EtaProgressController 的公開介面啟動
        # session，不再直接觸碰 MainWindow 內部屬性
        self.main_window.eta_ctrl.start_session()

        # ==========================================
        # [新增] ETA 預估時間專用變數 (滑動視窗測速)
        # ==========================================
        last_update_time = [time.time()]
        last_current = [0]
        speed_history = []  # 儲存最近 5 次的「每張圖耗時(秒)」

        def callback(current, total, msg):
            # ── [暫停 / 取消 檢查點] ───────────────────────────
            # _resume_event.wait() 在「已設定（執行中）」時立即返回，
            # 在「已清除（暫停）」時阻塞此執行緒，直到 MainWindow 呼叫 set()。
            self._resume_event.wait()
            if self._cancelled:
                raise InterruptedError("Scan cancelled by user")
            # ────────────────────────────────────────────────────

            now = time.time()
            elapsed = now - last_update_time[0]
            processed = current - last_current[0]

            # 1. 紀錄動態速度 (只保留最近 5 次)
            if processed > 0:
                sec_per_item = elapsed / processed
                speed_history.append(sec_per_item)
                if len(speed_history) > 5:
                    speed_history.pop(0)

            last_update_time[0] = now
            last_current[0] = current

            clean_msg = msg.replace("...", "")
            mode = self.main_window.eta_ctrl.mode

            if current < total:
                if len(speed_history) >= 2:
                    avg_sec_per_item = sum(speed_history) / len(speed_history)
                    t_real = (total - current) * avg_sec_per_item

                    if mode == 1:
                        # 模式 1：真實時間跳動——直接 emit，不經 PID
                        self.eta_updated.emit(t_real)
                        _ms = int(t_real * 1000)
                        _h, _ms = divmod(_ms, 3600000)
                        _m, _ms = divmod(_ms, 60000)
                        _s, _ms = divmod(_ms, 1000)
                        final_msg = f"{clean_msg} (剩餘: {_h:02d}:{_m:02d}:{_s:02d}:{_ms:03d})"

                    elif mode == 2:
                        # 模式 2：僅傳送 T_real，顯示由主執行緒 PID timer 控制
                        self.eta_updated.emit(t_real)
                        final_msg = clean_msg

                    elif mode == 3:
                        # 模式 3：累計張數，不顯示時間
                        self.eta_updated.emit(-1.0)
                        final_msg = f"{current} / {total} 張"

                    else:
                        # 模式 4：測試——印終端並顯示占位文字
                        self.eta_updated.emit(-1.0)
                        print(f"[ETA Mode 4] current={current} total={total} "
                              f"t_real={t_real:.2f}s msg={clean_msg}")
                        final_msg = f"{clean_msg} (Mode 4 Testing...)"

                else:
                    # 暖機中——樣本不足
                    self.eta_updated.emit(-1.0)
                    if mode == 3:
                        final_msg = f"{current} / {total} 張"
                    else:
                        final_msg = f"{clean_msg} (計算估時中...)"
            else:
                self.eta_updated.emit(0.0)
                final_msg = f"{clean_msg} (儲存資料庫中...)"

            self.progress_update.emit(current, total)
            self.status_update.emit(final_msg)

        try:
            #  [關鍵修復] 以前這裡是 .engine.model (因為改版變成 None 了)
            # 現在明確指定借用主程式的 clip_image_session！
            shared_model = self.main_window.engine.clip_image_session
            shared_preprocess = self.main_window.engine.preprocess

            shared_ocr_engines = self.main_window.engine.shared_ocr_engines

            # [修正] 傳入雙軌參數與 mapping
            self.service.run_ai_processing(
                files_full, files_emb_only, files_ocr_only, folder_ocr_map,
                progress_callback=callback, shared_model=shared_model, shared_preprocess=shared_preprocess,
                shared_ocr_engines=shared_ocr_engines
            )
            self.status_update.emit("Indexing completed."); self.all_finished.emit()
        except InterruptedError:
            # 使用者主動取消（非錯誤）
            print("[IndexerWorker] 掃描已由使用者取消。")
            self.status_update.emit("掃描已取消。")
            self.all_finished.emit()
        except Exception as e:
            print(f"Indexing Error: {e}"); self.status_update.emit("Indexing Error.")

class SearchWorker(QThread):
    batch_ready = pyqtSignal(list)
    finished_search = pyqtSignal(float, int)

    def __init__(self, engine, query, top_k, search_mode="text", use_ocr=True, weight_config=None, folder_path=None):
        super().__init__()
        self.engine = engine
        self.query = query
        self.top_k = top_k
        self.search_mode = search_mode
        self.use_ocr = use_ocr
        self.weight_config = weight_config
        self.folder_path = folder_path

    def run(self):
        start_time = time.time()
        if self.search_mode == "image":
            raw_results = self.engine.search_image(self.query, self.top_k, folder_path=self.folder_path)
        elif self.search_mode == "multi_vector":
            #  [新增] 多向量運算分支
            raw_results = self.engine.search_multi_vector(
                self.query['pos'], self.query['neg'], self.top_k, folder_path=self.folder_path
            )
        else:
            raw_results = self.engine.search_hybrid(
                self.query, self.top_k, self.use_ocr, self.weight_config, folder_path=self.folder_path
            )

        self.batch_ready.emit(raw_results)
        self.finished_search.emit(time.time() - start_time, len(raw_results))


class ONNXExportWorker(QThread):
    progress_update = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool)

    def __init__(self, model_name, pretrained):
        super().__init__()
        self.model_name = model_name
        self.pretrained = pretrained
        self.save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "onnx_clip")

    def run(self):
        try:
            # 傳入 self.progress_update.emit 當作 callback，即時回傳進度
            success = export_to_onnx(
                self.model_name, self.pretrained, self.save_dir,
                progress_callback=self.progress_update.emit
            )
            self.finished_signal.emit(success)
        except Exception as e:
            self.progress_update.emit(0, f"Error: {str(e)}")
            self.finished_signal.emit(False)

class OCRImportWorker(QThread):
    """[離線版] 從本地的 ZIP 擴充包解壓縮，取代原本的網路下載"""
    progress_update = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str, str) # success, lang_code, message

    def __init__(self, lang_code, zip_path):
        super().__init__()
        self.lang_code = lang_code
        self.zip_path = zip_path
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.models_dir = os.path.join(self.base_dir, "models", "ocr")

    def run(self):
        try:
            import zipfile
            lang_dir = os.path.join(self.models_dir, self.lang_code)
            common_dir = os.path.join(self.models_dir, "common")
            os.makedirs(lang_dir, exist_ok=True)
            os.makedirs(common_dir, exist_ok=True)

            self.progress_update.emit(10, "正在解壓縮本地模型包...")

            with zipfile.ZipFile(self.zip_path, 'r') as zip_ref:
                # 簡單的進度模擬
                file_list = zip_ref.namelist()
                total_files = len(file_list)
                for i, file in enumerate(file_list):
                    zip_ref.extract(file, self.models_dir)
                    percent = int(10 + (i / total_files) * 80)
                    self.progress_update.emit(percent, f"解壓縮中... ({percent}%)")

            self.progress_update.emit(100, "模型包匯入完成！")
            self.finished_signal.emit(True, self.lang_code, "本地模型匯入成功！可以開始使用了。")

        except Exception as e:
            self.finished_signal.emit(False, self.lang_code, f"匯入發生錯誤:\n{str(e)}")
