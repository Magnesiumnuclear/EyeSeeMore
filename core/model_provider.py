"""
ModelProvider — 獨立的模型加載與共享管理

職責：
  - 非阻塞加載 CLIP 模型（ONNX）與 Tokenizer
  - 管理共享的 OCR 引擎快取
  - 提供統一的模型存取介面
  - 發射 models_loaded / models_load_failed 訊號

設計意圖：
  解耦 ImageSearchEngine 與模型加載生命週期，
  使 IndexerWorker 能獨立啟動，不被模型加載阻擋。
"""

import os
import threading
import onnxruntime as ort
from PyQt6.QtCore import QObject, pyqtSignal


class ModelProvider(QObject):
    """
    模型加載與共享提供者（QObject 以使用 pyqtSignal）

    訊號：
      - models_loaded() ： 模型加載完成
      - models_load_failed(error_msg: str) ： 模型加載失敗
    """

    models_loaded = pyqtSignal()
    models_load_failed = pyqtSignal(str)

    def __init__(self, config, parent=None):
        """
        初始化模型提供者

        Args:
            config: ConfigManager 實例
            parent: Qt 父物件
        """
        super().__init__(parent)

        self.config = config
        self.device = "dml" if 'DmlExecutionProvider' in ort.get_available_providers() else "cpu"

        # 模型實例（初始為 None，加載後才填入）
        self.clip_image_session = None
        self.clip_text_session = None
        self.tokenizer = None
        self.preprocess = None
        self.is_hf_tokenizer = False

        # OCR 引擎共享快取（lang → engine）
        self.shared_ocr_engines = {}

        self._load_thread = None
        self._is_loading = False

    @property
    def is_ready(self) -> bool:
        """檢查模型是否加載完成"""
        return (
            self.clip_image_session is not None
            and self.clip_text_session is not None
            and self.tokenizer is not None
        )

    @property
    def is_loading(self) -> bool:
        """檢查是否正在加載中"""
        return self._is_loading

    def load_models_async(self):
        """
        在背景執行緒中非阻塞地加載模型

        立刻返回，加載在背景進行。
        完成後發射 models_loaded 或 models_load_failed 訊號。
        """
        if self._is_loading or self.is_ready:
            # 已經在加載或已經加載完成，不重複啟動
            return

        self._is_loading = True
        self._load_thread = threading.Thread(target=self._load_worker, daemon=True)
        self._load_thread.start()

    def _load_worker(self):
        """背景執行緒工作函式：執行模型加載"""
        try:
            self._load_models_impl()
            # ✅ 加載成功，發射訊號（Qt 會自動切到主執行緒）
            self.models_loaded.emit()
        except Exception as e:
            print(f"[ModelProvider] 加載失敗: {e}")
            import traceback
            traceback.print_exc()
            # ❌ 加載失敗，發射錯誤訊號
            self.models_load_failed.emit(str(e))
        finally:
            self._is_loading = False

    def _load_models_impl(self):
        """
        [內部] 執行模型加載的實際邏輯

        此方法在背景執行緒中運行，所有 I/O 不會阻塞主執行緒。
        """
        print(f"[ModelProvider] 開始加載 ONNX CLIP 模型...")

        model_name = self.config.get("model_name")
        pretrained = self.config.get("pretrained")

        # ── 1. 載入預處理器 ────────────────────────────────────
        from indexer import NumpyPreprocess
        self.preprocess = NumpyPreprocess(size=224)

        # ── 2. 載入 Tokenizer ─────────────────────────────────
        self.is_hf_tokenizer = (
            "roberta" in model_name.lower() or "xlm" in model_name.lower()
        )

        # [離線化修改] 強制讀取本地目錄，完全阻斷 Hugging Face 連線
        from transformers import AutoTokenizer, CLIPTokenizer
        from pathlib import Path as _Path

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        if self.is_hf_tokenizer:
            tok_path = _Path(os.path.join(base_dir, "models", "tokenizers", "xlm-roberta"))
            self.tokenizer = AutoTokenizer.from_pretrained(tok_path, local_files_only=True)

            # 手動補上 pad_token，解決離線載入報錯
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token or "<pad>"
        else:
            tok_path = _Path(os.path.join(base_dir, "models", "tokenizers", "openai-clip"))
            self.tokenizer = CLIPTokenizer.from_pretrained(tok_path, local_files_only=True)

            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token or "<|endoftext|>"

        # ── 3. 載入 ONNX 模型 Sessions ──────────────────────────
        print(f"[ModelProvider] 載入 ONNX 模型：{model_name}...")

        img_onnx_path = os.path.join(base_dir, "models", "onnx_clip", f"{model_name}_image.onnx")
        txt_onnx_path = os.path.join(base_dir, "models", "onnx_clip", f"{model_name}_text.onnx")

        # 設定推論提供者（優先 GPU/DML，退而求其次 CPU）
        providers = (
            ['DmlExecutionProvider', 'CPUExecutionProvider']
            if self.device == 'dml'
            else ['CPUExecutionProvider']
        )

        self.clip_image_session = ort.InferenceSession(img_onnx_path, providers=providers)
        self.clip_text_session = ort.InferenceSession(txt_onnx_path, providers=providers)

        print(f"[ModelProvider] ONNX 模型加載完成 (Device: {self.device})")

    def get_ocr_engine(self, lang: str):
        """
        取得指定語言的 OCR 引擎（Lazy Load）

        如果尚未加載該語言，會在此函式中即時加載並快取。

        Args:
            lang: 語言代碼 (e.g., "ch_sim", "en")

        Returns:
            加載好的 ONNXOCR 實例，或 None（加載失敗時）
        """
        if lang in self.shared_ocr_engines:
            return self.shared_ocr_engines[lang]

        # Lazy Load：第一次使用該語言時才加載
        try:
            from onnx_ocr import ONNXOCR
            engine = ONNXOCR(lang=lang, use_gpu=(self.device == 'dml'))
            self.shared_ocr_engines[lang] = engine
            print(f"[ModelProvider] ✅ OCR 引擎加載完成 ({lang})")
            return engine
        except Exception as e:
            print(f"[ModelProvider] ❌ OCR 引擎加載失敗 ({lang}): {e}")
            return None

    def wait_until_ready(self, timeout: float = 300.0) -> bool:
        """
        (可選) 阻塞式等待模型加載完成

        用於需要同步保證模型就緒的場景（如 test code）。
        一般應使用 models_loaded 訊號取代。

        Args:
            timeout: 最長等待秒數 (預設 5 分鐘)

        Returns:
            True 加載成功；False 超時或失敗
        """
        import time
        start_time = time.time()

        while not self.is_ready:
            if time.time() - start_time > timeout:
                return False
            time.sleep(0.1)

        return True
