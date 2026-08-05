import os
import sqlite3
import hashlib
from PIL import Image, ExifTags, ImageOps
from PIL import Image
import numpy as np
import logging
import json
import datetime
import psutil
import onnxruntime as ort  # <--- 新增
from onnx_ocr import ONNXOCR
import cv2


# ==========================================
# [新增] 讀取照片原始尺寸與 EXIF 旋轉標記
# ==========================================
def get_image_metadata(path):
    w, h, orientation = 0, 0, 1
    try:
        with Image.open(path) as pil_img:
            w, h = pil_img.size
            exif = pil_img.getexif()
            if exif:
                for k, v in exif.items():
                    if ExifTags.TAGS.get(k) == 'Orientation':
                        orientation = v
                        break
    except:
        pass
    return w, h, orientation

# ==========================================
# [新增] 根據 EXIF 將 OCR 原始座標翻轉為視覺正確座標
# ==========================================
def rotate_ocr_box(box, orientation, raw_w, raw_h):
    if orientation == 1: return box
    new_box = []
    for pt in box:
        x, y = pt[0], pt[1]
        if orientation == 2:   nx, ny = raw_w - x, y
        elif orientation == 3: nx, ny = raw_w - x, raw_h - y
        elif orientation == 4: nx, ny = x, raw_h - y
        elif orientation == 5: nx, ny = y, x
        elif orientation == 6: nx, ny = raw_h - y, x
        elif orientation == 7: nx, ny = raw_h - y, raw_w - x
        elif orientation == 8: nx, ny = y, raw_w - x
        else:                  nx, ny = x, y
        new_box.append([nx, ny])
    return new_box

# ==========================================
# [新增] 透明度安全的 RGB 轉換：將 RGBA/LA/P 合成至白色背景，避免透明像素變黑
# ==========================================
def pil_to_rgb_safe(pil_img, bg=(255, 255, 255)):
    mode = pil_img.mode
    if mode == 'P':
        pil_img = pil_img.convert('RGBA')
        mode = 'RGBA'
    if mode in ('RGBA', 'LA'):
        background = Image.new('RGB', pil_img.size, bg)
        alpha = pil_img.split()[-1]
        background.paste(pil_img.convert('RGB'), mask=alpha)
        return background
    return pil_img.convert('RGB')

# ==========================================
# [極速版] 純 Numpy + OpenCV 的圖片預處理 (完全取代 PIL)
# ==========================================
class NumpyPreprocess:
    def __init__(self, size=224):
        self.size = size
        self.mean = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32).reshape(3, 1, 1)
        self.std = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32).reshape(3, 1, 1)

    def __call__(self, image: Image.Image):
        # 🌟 0. 瞬間將 PIL 圖片無損轉入 Numpy 陣列 (此時為 RGB 格式)
        img_arr = np.array(image)
        h, w = img_arr.shape[:2]

        # 🌟 1. 智慧縮放 (短邊對齊 224)
        if w < h:
            new_w = self.size
            new_h = max(self.size, int(h * (self.size / w)))
        else:
            new_h = self.size
            new_w = max(self.size, int(w * (self.size / h)))
            
        # 使用 OpenCV 的 C++ 底層 SIMD 指令集進行極速縮放
        # INTER_CUBIC 能保持與原本 CLIP 模型訓練時相同的像素採樣品質
        img_arr = cv2.resize(img_arr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

        # 🌟 2. 記憶體視圖裁切 (View Slicing)
        # Numpy 的切片是 O(1) 操作，不複製記憶體，比 PIL.crop 瞬間完成
        top = (new_h - self.size) // 2
        left = (new_w - self.size) // 2
        img_arr = img_arr[top:top + self.size, left:left + self.size]

        # 🌟 3. 轉 Numpy、歸一化、調換維度為 CHW
        img_arr = img_arr.astype(np.float32) / 255.0
        img_arr = img_arr.transpose((2, 0, 1))
        img_arr = (img_arr - self.mean) / self.std
        
        return img_arr

# ==========================================
# [新增] L2 磁碟縮圖快取生成器
# ==========================================
def generate_l2_cache(img, original_path):
    """將記憶體中的圖片縮小並存入 .cache/thumbnails（保留透明通道）"""
    try:
        from core.paths import THUMBNAIL_CACHE_DIR as cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        
        # 使用 MD5 雜湊原始路徑作為安全檔名
        path_hash = hashlib.md5(original_path.encode('utf-8')).hexdigest()
        cache_path = os.path.join(cache_dir, f"{path_hash}.webp")
        
        if not os.path.exists(cache_path):
            # 複製一份影像進行縮放 (256x256 足夠涵蓋各種卡片比例)
            thumb = img.copy()
            thumb.thumbnail((256, 256), Image.Resampling.BICUBIC)
            # 保留透明通道：RGBA/LA/P 統一轉為 RGBA 存入 WebP
            if thumb.mode in ('RGBA', 'LA', 'P'):
                thumb = thumb.convert('RGBA')
            thumb.save(cache_path, format="WEBP", quality=80)
    except Exception as e:
        perf_print(f"L2 快取生成失敗: {e}")

# ==========================================
# [新增] 效能監控「總開關」與動態工具
# ==========================================
# 總開關：設為 True 啟動所有效能 X 光機，設為 False 徹底安靜且零效能負擔
ENABLE_PROFILING = False  

def perf_print(*args, **kwargs):
    """自訂列印函數：只有在開啟效能監控時才會印出東西"""
    if ENABLE_PROFILING:
        print(*args, **kwargs)

def optional_mem_profile(func):
    """自訂裝飾器：動態決定是否要掛載 memory_profiler"""
    if ENABLE_PROFILING:
        from memory_profiler import profile
        return profile(func)
    return func

import psutil
# 已經全面改用 ONNX，不再需要 torch 的效能監控
# from torch.profiler import profile as torch_profile, record_function, ProfilerActivity
# ==========================================


def _pipelined(items, fn, workers, max_inflight):
    """以 workers 條執行緒平行對 items 套用 fn，依「原順序」yield 結果。

    最多保持 max_inflight 個任務在處理中（背壓），避免一次把所有前處理結果塞滿記憶體。
    fn 內部應自行 try/except 並對失敗回傳 None；消費端負責略過 None。

    這讓「CPU 前處理（解碼／縮放／正規化／OCR BGR）」能與消費端的「GPU 推論 + DB 寫入」
    重疊（pipelining）：當主執行緒在跑當前批的 GPU 推論時，背景執行緒已在準備後續的圖。
    """
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor

    if not items:
        return
    workers = max(1, int(workers))
    max_inflight = max(workers + 1, int(max_inflight))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        it = iter(items)
        futures = deque()
        for _ in range(max_inflight):
            try:
                futures.append(ex.submit(fn, next(it)))
            except StopIteration:
                break
        while futures:
            fut = futures.popleft()
            try:
                futures.append(ex.submit(fn, next(it)))
            except StopIteration:
                pass
            yield fut.result()  # fn 已吞例外回傳 None，此處不會 re-raise


class IndexerService:
    def __init__(self, db_path, model_name='xlm-roberta-large-ViT-H-14', pretrained_name='frozen_laion5b_s13b_b90k', use_gpu_ocr=False, perf_config=None):
        self.db_path = db_path
        self.model_name = model_name
        self.pretrained_name = pretrained_name
        self.use_gpu_ocr = bool(use_gpu_ocr)
        self.device = "dml" if 'DmlExecutionProvider' in ort.get_available_providers() else "cpu"

        # ==========================================
        # 效能參數：從 perf_config 讀取，未設定時用安全預設值
        # ==========================================
        cfg = perf_config or {}
        self.batch_size       = int(cfg.get("indexing_batch_size",  4))
        self.commit_threshold = int(cfg.get("db_commit_threshold",  24))
        # [Perf Phase 3-I] 前處理平行度：解碼/縮放/正規化屬 I/O+SIMD（會釋放 GIL），
        # 多執行緒平行前處理並向前預取，可與 GPU 推論重疊（pipelining）。
        # 實測 CPU 前處理約為 GPU 推論的 3 倍且原為序列執行，這是向量建立的主要瓶頸。
        self.preprocess_workers = int(cfg.get("preprocess_workers", min(8, (os.cpu_count() or 4))))

        # [修改] 使用 perf_print 取代一般的 print
        perf_print(f"\n{'='*50}")
        perf_print(f"[系統硬體] AI 初始化檢查")
        perf_print(f"{'='*50}")

        # ONNX Runtime 設備狀態印出
        perf_print(f"[OCR  設備] 使用者設定: {'GPU' if self.use_gpu_ocr else 'CPU'} (ONNX Runtime)")
        perf_print(f"[CLIP 設備] 系統支援最高硬體: {self.device.upper()}")
        perf_print(f"[效能參數] batch_size={self.batch_size}  commit_threshold={self.commit_threshold}")
        perf_print(f"{'='*50}\n")

        logging.getLogger("ppocr").setLevel(logging.ERROR)

    def _get_conn(self):
        # 🌟 1. 加入 timeout (15秒)，當遇到極端讀寫衝突時允許等待，避免直接閃退
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        # 🌟 2. 啟動 WAL 模式 (Write-Ahead Logging)，實現前端讀取與後台寫入完全平行！
        conn.execute("PRAGMA journal_mode=WAL;")
        # 🌟 3. 放寬硬碟同步限制，讓作業系統在背景慢慢寫入，瞬間提升 10 倍 I/O 速度！
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self):
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir): os.makedirs(db_dir)
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # 1. 建立主檔案表 (🌟 新增 width, height, file_size 欄位，移除 ocr_text, ocr_data)
        cursor.execute('''CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            file_path TEXT UNIQUE, 
            filename TEXT, 
            folder_path TEXT, 
            mtime REAL,
            width INTEGER,
            height INTEGER,
            file_size INTEGER
        )''')
        
        # ==========================================
        # 🌟 自動資料庫遷移 (Migration)
        # ==========================================
        cursor.execute("PRAGMA table_info(files)")
        columns = [info[1] for info in cursor.fetchall()]

        # A. 補齊缺失的寬高與大小欄位 (針對舊資料庫)
        if 'width' not in columns:
            perf_print("[Indexer] 升級資料庫：新增尺寸與大小欄位...")
            cursor.execute("ALTER TABLE files ADD COLUMN width INTEGER")
            cursor.execute("ALTER TABLE files ADD COLUMN height INTEGER")
            cursor.execute("ALTER TABLE files ADD COLUMN file_size INTEGER")

        # B. 砍掉殘留的 OCR 欄位 (瘦身)
        if 'ocr_text' in columns:
            try:
                perf_print("[Indexer] 升級資料庫：清除殘留的舊版 OCR 欄位...")
                cursor.execute("ALTER TABLE files DROP COLUMN ocr_text")
                cursor.execute("ALTER TABLE files DROP COLUMN ocr_data")
            except Exception as e:
                perf_print(f"[Indexer] 欄位清理略過 (SQLite 版本可能過舊不支援 DROP COLUMN): {e}")
        # ==========================================
        
        # 2. 建立 CLIP 向量表
        cursor.execute('''CREATE TABLE IF NOT EXISTS embeddings (file_id INTEGER, model_name TEXT, embedding BLOB, PRIMARY KEY (file_id, model_name), FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE)''')
        
        # 3. 建立統計表
        cursor.execute('''CREATE TABLE IF NOT EXISTS model_stats (model_name TEXT, folder_path TEXT, image_count INTEGER, last_scanned TEXT, PRIMARY KEY (model_name, folder_path))''')
        
        # ==========================================
        # 🌟 階段一實作：建立虛擬資料夾 (Collections) 系統
        # ==========================================
        # 5. 虛擬資料夾本身 (支援自訂名稱)
        cursor.execute('''CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT UNIQUE, 
            created_at REAL
        )''')
        
        # 6. 虛擬資料夾與圖片的對應關係表 
        # (我們刻意使用 file_path 關聯，這樣就算實體圖片被暫時移出索引，標籤關聯也不會斷掉)
        cursor.execute('''CREATE TABLE IF NOT EXISTS collection_items (
            collection_id INTEGER, 
            file_path TEXT, 
            PRIMARY KEY (collection_id, file_path), 
            FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
        )''')

        # 7. 釘選圖(Pinned) — 只存需要釘選的圖片路徑，不對每張圖片建立欄位
        cursor.execute('''CREATE TABLE IF NOT EXISTS pinned (
            file_path TEXT PRIMARY KEY
        )''')

        # 8. OCR 結果表（多語系，每張圖片可有多筆記錄）
        cursor.execute('''CREATE TABLE IF NOT EXISTS ocr_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            lang TEXT,
            ocr_text TEXT,
            ocr_data TEXT,
            confidence REAL,
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        )''')

        # 9. 二級索引
        # ocr_results.file_id 沒有索引時，files 的 ON DELETE CASCADE
        # 會對 ocr_results 逐檔全表掃描（實測 8k 圖刪 300 檔需 1.7 秒，
        # 加索引後 3ms）；軌道 C 批查與預覽 OCR 框 JOIN 同樣受惠。
        # 注意：勿加 embeddings(model_name) 索引——實測反而拖慢
        # update_folder_stats 的 GROUP BY JOIN，且 scan 過濾選擇度太低無益。
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ocr_file_id ON ocr_results(file_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder_path)')

        conn.commit()
        return conn

    def scan_for_new_files(self, source_folders_config, prune_missing=True):
        if not source_folders_config: return [], [], [], 0, {}

        folder_ocr_map = {}
        # tuple 形式供 str.endswith 一次比對(比 os.path.splitext 配置字串更省)
        valid_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
        disk_paths = set()

        # [Perf] 預先聚合本次需要的 OCR 語系;若為空代表沒有任何資料夾啟用 OCR,
        # 後續可整段跳過 ocr_results 載入與比對。
        needed_langs = set()
        for f_conf in source_folders_config:
            folder = os.path.normpath(f_conf["path"])
            enabled_langs = f_conf.get("enabled_langs", [])
            folder_ocr_map[folder] = enabled_langs
            needed_langs.update(enabled_langs)

        # [Debug 日誌 1] 檢查從主程式傳遞過來的資料夾設定是否正確
        print(f"\n[Debug] 目前資料夾的 OCR 設定: {folder_ocr_map}")

        # [變更偵測] 走訪磁碟時順手把每張圖的 mtime 記下來(路徑 -> mtime)。
        # 這裡改用 os.scandir 手動遞迴而非 os.walk:目錄列舉本身就已取得 stat 資料,
        # entry.stat() 直接讀快取等於「白拿」mtime,不必為每張已索引的圖片
        # 在比對階段再額外做一次 os.stat。
        disk_mtimes = {}
        for folder in folder_ocr_map.keys():
            if not os.path.exists(folder): continue
            stack = [folder]
            while stack:
                current_dir = stack.pop()
                try:
                    with os.scandir(current_dir) as it:
                        for entry in it:
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    stack.append(entry.path)
                                elif entry.name.lower().endswith(valid_extensions):
                                    full_path = os.path.normpath(entry.path)
                                    disk_paths.add(full_path)
                                    disk_mtimes[full_path] = entry.stat().st_mtime
                            except OSError:
                                continue  # 單一檔案讀取失敗(權限/掃描中被移除)不影響整體
                except OSError:
                    continue  # 無法列舉的資料夾直接跳過

        conn = self.init_db()
        cursor = conn.cursor()

        # 1. 取得 DB 所有檔案(一併取出 mtime,供下方變更偵測比對)
        cursor.execute("SELECT id, file_path, mtime FROM files")
        db_files = {os.path.normpath(row[1]): (row[0], row[2]) for row in cursor.fetchall()}
        db_paths = set(db_files.keys())
        
        # 2. 取得有 CLIP 向量的檔案
        cursor.execute("SELECT file_id FROM embeddings WHERE model_name = ?", (self.model_name,))
        db_has_emb = set(row[0] for row in cursor.fetchall())
        
        # 3. 取得各檔「已完成」的 OCR 語系
        # [Perf] 沒有任何資料夾啟用 OCR 時,完全跳過載入整張 ocr_results;
        # 有需要時也只撈本次相關語系(WHERE lang IN ...),減少掃描列數與記憶體。
        ocr_history = {}
        if needed_langs:
            _nl = list(needed_langs)
            _ph = ','.join(['?'] * len(_nl))
            cursor.execute(
                f"SELECT file_id, lang FROM ocr_results WHERE lang IN ({_ph})", _nl)
            for file_id, lang in cursor.fetchall():
                ocr_history.setdefault(file_id, set()).add(lang)
            
        # [Debug 日誌 2] 檢查資料庫讀取狀況
        print(f"[Debug] 資料庫狀態 -> 總圖片數: {len(db_files)}, 有 CLIP 向量: {len(db_has_emb)}, 有 OCR 紀錄的圖片數: {len(ocr_history)}")
        
        # [安全] 刪除偵測是「全庫性」的(db_paths - disk_paths)。逐資料夾掃描時
        # disk_paths 只含單一資料夾,必須關閉(prune_missing=False),否則會把
        # 其他資料夾的檔案全部誤判為已刪而清除。全量掃描才用預設 True。
        if prune_missing:
            to_delete = db_paths - disk_paths
            deleted_count = len(to_delete)
            if to_delete:
                to_delete_list = list(to_delete)
                BATCH = 900
                for i in range(0, len(to_delete_list), BATCH):
                    batch = to_delete_list[i:i+BATCH]
                    placeholders = ','.join(['?'] * len(batch))
                    cursor.execute(f"DELETE FROM files WHERE file_path IN ({placeholders})", batch)
                conn.commit()
        else:
            deleted_count = 0
            
        # ==========================================
        # 🌟 [變更偵測] 原地覆蓋的圖片(裁切/旋轉/重新匯出:路徑沒變但內容變了)
        # ==========================================
        # 這種圖的 CLIP 向量、OCR 文字與寬高全部過期,必須重跑。
        # [關鍵] 不刪 files 列:若在掃描階段就刪掉舊列,接下來的索引一旦被取消
        # 或中途失敗,這張圖會連同 cascade 的 embeddings/ocr_results 一起從圖庫
        # 與搜尋結果中消失,等於用 mtime 比對換來資料遺失。
        # 改為只失效「衍生資料」:刪掉 embeddings / ocr_results、把 width/height/
        # file_size 清成 NULL,files 列本身保留 → 圖片在 UI 上永不消失。
        # 清掉向量後該圖自然落入軌道 B、清掉 OCR 後落入軌道 C、寬高清 NULL 後
        # 由軌道 D 補回,完全沿用既有分流,不需要新軌道。
        # mtime 在此一併更新;就算重跑失敗也不影響重試,因為分流依據是
        # 「有沒有向量」而不是 mtime。
        # 容差 1 秒:mtime 是浮點數,不同檔案系統(NTFS/FAT/網路磁碟)精度也不同,
        # 硬性相等比對會讓每次掃描都誤判成變更而無限重索引。
        MTIME_TOLERANCE = 1.0
        common_paths = disk_paths & db_paths
        files_changed = []
        for p in common_paths:
            disk_mtime = disk_mtimes.get(p)
            db_mtime = db_files[p][1]
            # 任一邊拿不到 mtime(舊資料列為 NULL/檔案 stat 失敗)就不做判定,維持原行為
            if disk_mtime is None or db_mtime is None:
                continue
            if abs(disk_mtime - db_mtime) > MTIME_TOLERANCE:
                files_changed.append(p)

        if files_changed:
            BATCH = 900
            for i in range(0, len(files_changed), BATCH):
                batch = files_changed[i:i+BATCH]
                ids = [db_files[p][0] for p in batch]
                placeholders = ','.join(['?'] * len(ids))
                # 內容已變 → 所有模型的向量與所有語系的 OCR 一律失效
                cursor.execute(
                    f"DELETE FROM embeddings WHERE file_id IN ({placeholders})", ids)
                cursor.execute(
                    f"DELETE FROM ocr_results WHERE file_id IN ({placeholders})", ids)
                # 寬高/檔案大小清空交由軌道 D 補回,同時寫入新的 mtime
                cursor.executemany(
                    "UPDATE files SET mtime = ?, width = NULL, height = NULL,"
                    " file_size = NULL WHERE id = ?",
                    [(disk_mtimes[p], db_files[p][0]) for p in batch])
            conn.commit()
            # 記憶體端同步:抽掉這些 file_id 的向量/OCR 紀錄,
            # 下方交叉比對才會把它們排進軌道 B / C 重跑
            for p in files_changed:
                fid = db_files[p][0]
                db_has_emb.discard(fid)
                ocr_history.pop(fid, None)

        files_full = list(disk_paths - db_paths) # 完全新圖(DB 中不存在的路徑)
        files_emb_only = []
        files_ocr_only = []

        # 交叉比對：找出缺 CLIP 或缺特定語系 OCR 的圖片
        # [Perf] p 來自 disk_paths∩db_paths,兩端皆已 normpath,走
        # _match_folder_langs_norm 免去每張圖重複正規化;無 OCR 需求時整段短路。
        check_ocr = bool(needed_langs)
        for p in common_paths:
            file_id = db_files[p][0]

            # 檢查是否缺 CLIP
            if file_id not in db_has_emb:
                files_emb_only.append(p)

            # 檢查 OCR (該資料夾勾選的 vs 該圖片實際跑過的)
            if check_ocr:
                required_langs = self._match_folder_langs_norm(p, folder_ocr_map)
                done_langs = ocr_history.get(file_id, set())
                # 只要有任何一個需要的語系沒跑過，就排入補算名單！
                if any(lang not in done_langs for lang in required_langs):
                    files_ocr_only.append(p)
                
        # [Debug 日誌 4] 最終分類結果(內容已變更的圖已失效衍生資料,併入 Emb/Ocr 軌道)
        print(f"[Debug] 掃描分類結果 -> 全新圖(Full): {len(files_full)}, 內容已變更需重算: {len(files_changed)}, 缺向量(Emb): {len(files_emb_only)}, 缺OCR(Ocr): {len(files_ocr_only)}\n")

        # ==========================================
        # 🌟 軌道 D (已搬家): 在這裡確保每次掃描都會補齊缺失的尺寸資訊！
        # ==========================================
        cursor.execute("SELECT id, file_path FROM files WHERE width IS NULL OR file_size IS NULL")
        missing_meta_rows = cursor.fetchall()
        meta_updates = []
        if missing_meta_rows:
            perf_print(f"[Indexer] 發現 {len(missing_meta_rows)} 張圖片缺少尺寸資訊，開始平行補齊...")

            def _read_one_meta(row):
                row_id, path = row
                try:
                    file_size = os.path.getsize(path)
                    # 讀取 EXIF 並依方向交換長寬(視覺正確尺寸)
                    raw_w, raw_h, orientation = get_image_metadata(path)
                    w, h = (raw_h, raw_w) if orientation in (5, 6, 7, 8) else (raw_w, raw_h)
                    return (w, h, file_size, row_id)
                except Exception:
                    return None

            # [Perf] 影像 header 讀取與 stat 屬 I/O 密集(讀檔/解碼會釋放 GIL),
            # 平行化可把這段一次性補齊時間縮短數倍。執行緒只做 FS/PIL 讀取,
            # 不碰 sqlite cursor,寫入仍集中在主執行緒,確保連線安全。
            if len(missing_meta_rows) > 1:
                from concurrent.futures import ThreadPoolExecutor
                workers = min(8, len(missing_meta_rows))
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    meta_updates = [r for r in ex.map(_read_one_meta, missing_meta_rows) if r]
            else:
                meta_updates = [r for r in map(_read_one_meta, missing_meta_rows) if r]

            if meta_updates:
                cursor.executemany(
                    "UPDATE files SET width=?, height=?, file_size=? WHERE id=?", meta_updates)
                conn.commit()
            perf_print(f"[Indexer] 已成功補齊 {len(meta_updates)} 張圖片的尺寸與大小資訊！")
        # ==========================================
        
        # [Perf] 索引內容無任何變動(無新增/補算/刪除/補欄位)時,統計必然不變,
        # 跳過 model_stats 的 JOIN+GROUP BY 重建,讓例行的無變更掃描幾乎零寫入。
        if (files_full or files_emb_only or files_ocr_only
                or deleted_count or meta_updates):
            self.update_folder_stats(conn)
        conn.close()

        return files_full, files_emb_only, files_ocr_only, deleted_count, folder_ocr_map

    def _match_folder_langs_norm(self, path_norm, folder_ocr_map):
        """最長前綴匹配,回傳該圖應套用的 OCR 語系清單。

        [Perf] 假設 path_norm 已是 os.path.normpath 的結果(掃描熱路徑使用),
        省去每張圖重複正規化;並先比長度(便宜)再比 startswith(較貴)。
        """
        matched_folder = ""
        enabled_langs = []
        for folder_path, langs in folder_ocr_map.items():
            if len(folder_path) > len(matched_folder) and path_norm.startswith(folder_path):
                matched_folder = folder_path
                enabled_langs = langs
        return enabled_langs

    def _get_folder_ocr_setting(self, path, folder_ocr_map):
        """對外相容介面:先正規化 path,再做最長前綴匹配。"""
        return self._match_folder_langs_norm(os.path.normpath(path), folder_ocr_map)

    # ==========================================
    # 🌟 [新增] 資料夾拆分任務:把多資料夾來源拆成可獨立執行的逐資料夾任務
    # ==========================================
    def split_into_folder_tasks(self, source_folders_config):
        """將多資料夾來源設定拆成「每個頂層資料夾一個獨立掃描任務」。

        用途:讓上層(如 IndexerWorker)能逐資料夾掃描/索引,取得每資料夾
        獨立的結果與進度,並支援單一資料夾的精準重掃。

        規則:
          • 以 normpath 去重(同一路徑只保留第一次出現)。
          • 巢狀歸併:被其他「已設定資料夾」包含的子資料夾不另開任務,而是
            併入其最頂層被設定祖先的任務,使各任務掃描範圍互斥、不重複走訪
            同一批檔案;同時把子資料夾設定一併放進該任務 config,scan 仍以
            最長前綴匹配保留子資料夾自身的 OCR 語系設定。

        Args:
            source_folders_config: 與 scan_for_new_files 相同格式的設定陣列。

        Returns:
            [{"path": 頂層資料夾(normpath),
              "enabled_langs": 該頂層資料夾語系,
              "config": [屬於此子樹的所有資料夾設定]}...];傳入空設定回傳 []。
        """
        if not source_folders_config:
            return []

        # 1. 正規化 + 去重(保留首次出現)
        norm_confs = []   # [(norm_path, conf)]
        seen = set()
        for fc in source_folders_config:
            n = os.path.normpath(fc["path"])
            if n in seen:
                continue
            seen.add(n)
            norm_confs.append((n, fc))

        norm_paths = [n for n, _ in norm_confs]

        def _has_ancestor(target):
            return any(target != m and target.startswith(m + os.sep) for m in norm_paths)

        # 2. 每個「沒有被設定祖先」的資料夾各成一個任務,蒐集其子樹下全部設定
        tasks = []
        for n, fc in norm_confs:
            if _has_ancestor(n):
                continue  # 併入祖先任務,不另開
            sub = [c for m, c in norm_confs if m == n or m.startswith(n + os.sep)]
            tasks.append({
                "path": n,
                "enabled_langs": fc.get("enabled_langs", []),
                "config": sub,
            })
        return tasks

    def scan_folder_task(self, task):
        """掃描單一資料夾任務(split_into_folder_tasks 回傳的元素之一)。

        回傳值格式與 scan_for_new_files 相同:
        (files_full, files_emb_only, files_ocr_only, deleted_count, folder_ocr_map)。

        注意:此處以 prune_missing=False 呼叫——逐資料夾掃描「不做」全庫刪除偵測,
        因為單一資料夾的 disk_paths 無法代表整個索引庫(否則會誤刪其他資料夾)。
        全庫的刪除清理請改用 scan_for_new_files(完整 config) 走預設 prune_missing=True。
        """
        return self.scan_for_new_files(task["config"], prune_missing=False)

    @optional_mem_profile
    def run_ai_processing(self, files_full, files_emb_only, files_ocr_only, folder_ocr_map, progress_callback=None, shared_model=None, shared_preprocess=None, shared_ocr_engines=None):
        if ENABLE_PROFILING:
            process = psutil.Process(os.getpid())
            start_mem = process.memory_info().rss / (1024 * 1024)
            perf_print(f"\n[系統資源] 開始處理前，程式佔用 RAM: {start_mem:.2f} MB")

        if not files_full and not files_emb_only and not files_ocr_only:
            return

        conn = self._get_conn() 
        cursor = conn.cursor()
        total_files = len(files_full) + len(files_emb_only) + len(files_ocr_only)
        current_progress = 0

        # ==========================================
        # 🌟 [新增] 延遲寫入計數器 (Lazy Commit)
        # ==========================================
        commit_counter = 0
        
        import gc

        # [註] 本次需要哪些 OCR 語系不必預先蒐集:軌道 A 與軌道 C 都在真正要用到時
        # 才呼叫 ensure_ocr_engine 做 Lazy Load(Phase 3-A),避免載入用不到的引擎佔 VRAM。

        try:
            # 載入 CLIP
            if shared_model and shared_preprocess:
                perf_print("[Indexer] Using shared OpenCLIP model from main engine.")
                model = shared_model
                preprocess = shared_preprocess
            else:
                model, preprocess, _ = self.load_ai_models(need_ocr=False)


            # [Refactor Phase 3-A] OCR 引擎改為 Lazy Load
            # 共享快取（來自 ModelProvider 或傳入的 shared_ocr_engines）
            ocr_engines = shared_ocr_engines if shared_ocr_engines is not None else {}

            # 本次任務中「載入失敗」的語系(模型檔缺失/VRAM 不足等)。
            # 只記在區域變數:同一次索引不再對每張圖重試昂貴的 ONNXOCR 建構，
            # 但下次任務仍會重新嘗試(使用者補上模型檔後即可自動恢復)。
            failed_ocr_langs = set()

            # 內部 Lazy Load 函式：當 OCR 引擎不存在時立即加載
            def ensure_ocr_engine(lang: str):
                """確保特定語言的 OCR 引擎已加載，若無則即時加載"""
                if lang not in ocr_engines:
                    if lang in failed_ocr_langs:
                        return False
                    try:
                        ocr_engines[lang] = ONNXOCR(lang=lang, use_gpu=self.use_gpu_ocr)
                        perf_print(f"[OCR Lazy Load] {lang} 引擎已加載")
                    except Exception as e:
                        failed_ocr_langs.add(lang)
                        print(f"[Warning] OCR 引擎載入失敗 ({lang}): {e}")
                        return False
                return lang in ocr_engines

        except Exception as e:
            print(f"Model Load Failed: {e}"); conn.close(); return

        # ==========================================
        # [Perf Phase 3-I] 平行前處理 + 管線化
        # CPU 前處理（解碼／EXIF／RGB／縮放／正規化／L2 縮圖／OCR BGR）實測約為 GPU 推論的
        # ~3 倍，且原為序列執行。以下用執行緒池平行做前處理並向前預取（pipelining）；
        # GPU 推論（_compute_clip）與 DB 寫入、OCR 推論則留在本（消費）執行緒序列進行——
        # ONNX session 與 sqlite 連線都只在單一執行緒被觸碰，確保安全。
        # ==========================================
        inflight = max(self.batch_size * 2, self.preprocess_workers + self.batch_size)

        # --- 軌道 A: 全新圖片 (OCR + CLIP) ---
        def _prep_full(path):
            """[背景執行緒] 單張全流程前處理；任何失敗回傳 None 由消費端略過。"""
            try:
                file_size = os.path.getsize(path)
                # 統一讀取中心：唯一一次觸碰硬碟，完成尺寸／EXIF／轉正／RGB
                with Image.open(path) as pil_img:
                    raw_w, raw_h = pil_img.size
                    orientation = 1
                    exif = pil_img.getexif()
                    if exif:
                        for k, v in exif.items():
                            if ExifTags.TAGS.get(k) == 'Orientation':
                                orientation = v
                                break
                    img_transposed = ImageOps.exif_transpose(pil_img)
                    img_rgb = pil_to_rgb_safe(img_transposed)
                w, h = (raw_h, raw_w) if orientation in (5, 6, 7, 8) else (raw_w, raw_h)
                generate_l2_cache(img_transposed, path)
                clip_input = np.expand_dims(preprocess(img_rgb), axis=0)
                # 僅當該圖所屬資料夾有啟用 OCR 時才備 BGR（省 cvtColor 與在途記憶體）
                required_langs = self._get_folder_ocr_setting(path, folder_ocr_map)
                img_bgr = cv2.cvtColor(np.array(img_rgb), cv2.COLOR_RGB2BGR) if required_langs else None
                meta = (path, os.path.basename(path), os.path.dirname(path),
                        os.path.getmtime(path), w, h, file_size)
                return {"path": path, "meta": meta, "clip": clip_input,
                        "bgr": img_bgr, "langs": required_langs}
            except Exception:
                return None

        def _flush_full(recs):
            """[消費執行緒] 將一批已備好的記錄寫入 files / embeddings / ocr_results。"""
            nonlocal commit_counter
            if not recs:
                return
            batch_paths = [r["path"] for r in recs]
            try:
                cursor.executemany(
                    'INSERT OR IGNORE INTO files (file_path, filename, folder_path, mtime, width, height, file_size) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    [r["meta"] for r in recs])
            except sqlite3.Error as e:
                print(f"DB Error: {e}")

            placeholders = ','.join(['?'] * len(batch_paths))
            cursor.execute(f"SELECT file_path, id FROM files WHERE file_path IN ({placeholders})", tuple(batch_paths))
            id_map = {row[0]: row[1] for row in cursor.fetchall()}

            # CLIP 向量（GPU，單執行緒）
            embeddings_list = self._compute_clip(model, [r["clip"] for r in recs])
            emb_insert_data = [(id_map.get(batch_paths[idx]), self.model_name, embeddings_list[idx])
                               for idx in range(len(batch_paths)) if id_map.get(batch_paths[idx]) is not None]
            try:
                cursor.executemany('INSERT OR IGNORE INTO embeddings (file_id, model_name, embedding) VALUES (?, ?, ?)', emb_insert_data)
            except sqlite3.Error:
                pass

            # OCR（BGR 已於前處理備妥；偵測/辨識推論留在本執行緒）
            ocr_insert_data = []
            for r in recs:
                file_id = id_map.get(r["path"])
                if not file_id or r["bgr"] is None:
                    continue
                img_bgr = r["bgr"]
                for target_lang in r["langs"]:
                    if ensure_ocr_engine(target_lang) and target_lang in ocr_engines:
                        ocr_text_final, ocr_data_final = "[NONE]", "[]"
                        ocr_result = ocr_engines[target_lang].ocr(img_bgr, cls=False)
                        if ocr_result and ocr_result[0]:
                            detected_text_list = []
                            json_data_list = []
                            for line in ocr_result[0]:
                                box, (text, conf) = line[0], line[1]
                                detected_text_list.append(text)
                                json_data_list.append({"box": [[int(pt[0]), int(pt[1])] for pt in box], "text": text, "conf": round(float(conf), 4)})
                            ocr_text_final = " ".join(detected_text_list)
                            ocr_data_final = json.dumps(json_data_list, ensure_ascii=False)
                        ocr_insert_data.append((file_id, target_lang, ocr_text_final, ocr_data_final, 1.0))
            if ocr_insert_data:
                cursor.executemany('INSERT INTO ocr_results (file_id, lang, ocr_text, ocr_data, confidence) VALUES (?, ?, ?, ?, ?)', ocr_insert_data)

            commit_counter += len(recs)
            if commit_counter >= self.commit_threshold:
                conn.commit()
                commit_counter = 0

        batch = []
        for rec in _pipelined(files_full, _prep_full, self.preprocess_workers, inflight):
            current_progress += 1
            if progress_callback and (current_progress % self.batch_size == 0):
                progress_callback(current_progress, total_files, f"Full AI: {current_progress}/{total_files}...")
            if rec is not None:
                batch.append(rec)
                if len(batch) >= self.batch_size:
                    _flush_full(batch); batch = []
        _flush_full(batch); batch = []

        # --- 軌道 B: 切換模型補算 (光速 CLIP) ---
        def _prep_emb(path):
            """[背景執行緒] 純 CLIP 補算的單張前處理；失敗回傳 None。"""
            try:
                with Image.open(path) as pil_img:
                    img_transposed = ImageOps.exif_transpose(pil_img)
                    generate_l2_cache(img_transposed, path)
                    img_rgb = pil_to_rgb_safe(img_transposed)
                return {"path": path, "clip": np.expand_dims(preprocess(img_rgb), axis=0)}
            except Exception:
                return None

        def _flush_emb(recs):
            """[消費執行緒] 將一批已備好的記錄寫入 embeddings。"""
            nonlocal commit_counter
            if not recs:
                return
            valid_paths = [r["path"] for r in recs]
            embeddings_list = self._compute_clip(model, [r["clip"] for r in recs])
            placeholders = ','.join(['?'] * len(valid_paths))
            cursor.execute(f"SELECT file_path, id FROM files WHERE file_path IN ({placeholders})", tuple(valid_paths))
            id_map = {row[0]: row[1] for row in cursor.fetchall()}
            emb_insert_data = [(id_map.get(p), self.model_name, embeddings_list[idx])
                               for idx, p in enumerate(valid_paths) if id_map.get(p) is not None]
            try:
                cursor.executemany('INSERT OR IGNORE INTO embeddings (file_id, model_name, embedding) VALUES (?, ?, ?)', emb_insert_data)
            except sqlite3.Error:
                pass
            commit_counter += len(recs)
            if commit_counter >= self.commit_threshold:
                conn.commit()
                commit_counter = 0

        for rec in _pipelined(files_emb_only, _prep_emb, self.preprocess_workers, inflight):
            current_progress += 1
            if progress_callback and (current_progress % self.batch_size == 0):
                progress_callback(current_progress, total_files, f"Fast CLIP: {current_progress}/{total_files}...")
            if rec is not None:
                batch.append(rec)
                if len(batch) >= self.batch_size:
                    _flush_emb(batch); batch = []
        _flush_emb(batch); batch = []

        # --- 軌道 C: 精準補算文字 (缺哪國補哪國) ---
        for i in range(0, len(files_ocr_only), self.batch_size):
            batch_paths = files_ocr_only[i : i + self.batch_size]
            if progress_callback: progress_callback(current_progress, total_files, f"Backfill OCR: {current_progress}/{total_files}...")

            # [效能優化] 批次查詢，消除 N+1 問題
            # 一次取得整個批次的 path→id 映射
            placeholders_c = ','.join(['?'] * len(batch_paths))
            cursor.execute(
                f"SELECT file_path, id FROM files WHERE file_path IN ({placeholders_c})",
                batch_paths
            )
            path_to_id = {row[0]: row[1] for row in cursor.fetchall()}

            # 一次取得這批 file_id 已完成的所有 OCR 語系
            batch_ids = list(path_to_id.values())
            id_to_done_langs: dict = {}
            if batch_ids:
                placeholders_id = ','.join(['?'] * len(batch_ids))
                cursor.execute(
                    f"SELECT file_id, lang FROM ocr_results WHERE file_id IN ({placeholders_id})",
                    batch_ids
                )
                for file_id, lang in cursor.fetchall():
                    id_to_done_langs.setdefault(file_id, set()).add(lang)

            ocr_insert_data = []
            for path in batch_paths:
                try:
                    file_id = path_to_id.get(path)
                    if not file_id: continue

                    # 🌟 統一讀取中心 (軌道 C 專用)
                    # exif_transpose 轉正後，OCR 輸出座標即為視覺正確座標，直接存入
                    with Image.open(path) as pil_img:
                        img_rgb = pil_to_rgb_safe(ImageOps.exif_transpose(pil_img))

                    # 轉換為 OCR 需要的 BGR 陣列
                    img_bgr = cv2.cvtColor(np.array(img_rgb), cv2.COLOR_RGB2BGR)

                    # 從記憶體 Dict 取出已完成語系（O(1)，不再查資料庫）
                    done_langs = id_to_done_langs.get(file_id, set())
                    required_langs = self._get_folder_ocr_setting(path, folder_ocr_map)
                    missing_langs = [l for l in required_langs if l not in done_langs]

                    # 針對缺少的語系補跑
                    for target_lang in missing_langs:
                        # [修正] 與軌道 A 一致:引擎沒載入就即時 Lazy Load。
                        # 先前這裡只檢查 ocr_engines,而「只補 OCR」的掃描根本不會經過軌道 A,
                        # 引擎因此永遠不會被載入 → 整條補算軌道靜默空轉、一列都寫不進去。
                        # 載入失敗(模型檔缺失)就跳過該語系:不寫入 ocr_results,
                        # 該圖下次掃描仍會被排進補算名單,不會被誤標為已完成。
                        if ensure_ocr_engine(target_lang) and target_lang in ocr_engines:
                            ocr_text_final, ocr_data_final = "[NONE]", "[]"

                            # 🌟 將陣列直接餵給 OCR 引擎！
                            ocr_result = ocr_engines[target_lang].ocr(img_bgr, cls=False)
                            if ocr_result and ocr_result[0]:
                                detected_text_list = []
                                json_data_list = []
                                for line in ocr_result[0]:
                                    box, (text, conf) = line[0], line[1]
                                    detected_text_list.append(text)
                                    json_data_list.append({"box": [[int(pt[0]), int(pt[1])] for pt in box], "text": text, "conf": round(float(conf), 4)})
                                ocr_text_final = " ".join(detected_text_list)
                                ocr_data_final = json.dumps(json_data_list, ensure_ascii=False)

                            ocr_insert_data.append((file_id, target_lang, ocr_text_final, ocr_data_final, 1.0))
                except Exception as e: print(f"Skipping OCR {path}: {e}")
            
            if ocr_insert_data:
                try:
                    cursor.executemany('INSERT INTO ocr_results (file_id, lang, ocr_text, ocr_data, confidence) VALUES (?, ?, ?, ?, ?)', ocr_insert_data)
                except sqlite3.Error as e: print(f"Update OCR Error: {e}")
                
            current_progress += len(batch_paths)

            commit_counter += len(batch_paths)
            if commit_counter >= self.commit_threshold:
                conn.commit()
                commit_counter = 0

        # ==========================================
        # 🌟 [新增] 所有軌道結束後，最後保底結帳
        # ==========================================
        if commit_counter > 0:
            conn.commit()

        self.update_folder_stats(conn)
        conn.close()

        # ==========================================
        # [修改 4] 任務結束，強制銷毀所有 OCR 引擎釋放 VRAM(💥 已廢棄)
        # ==========================================
        # 🌟🌟🌟 絕對不能清空！DirectML 銷毀 Session 會導致 GPU 狀態毒化
        # ocr_engines.clear()
        # gc.collect()
        perf_print("[Indexer] OCR 任務結束，模型實例已銷毀，VRAM 釋放完畢。")

        if ENABLE_PROFILING:
            end_mem = process.memory_info().rss / (1024 * 1024)
            perf_print(f"[系統資源] 處理結束後，程式佔用 RAM: {end_mem:.2f} MB (變化: {end_mem - start_mem:+.2f} MB)\n")

    def _compute_clip(self, image_session, batch_images):
        # [關鍵修改] 不再使用 torch.cat，改用純 Numpy 的 concatenate
        image_input_np = np.concatenate(batch_images, axis=0)
        
        perf_print(f"[張量追蹤] 目前計算批次 (Batch Size: {len(batch_images)}) 被送往 -> ONNX Runtime")
        input_name = image_session.get_inputs()[0].name
        image_features = image_session.run(None, {input_name: image_input_np})[0]
        image_features = image_features / np.linalg.norm(image_features, axis=-1, keepdims=True)
            
        return [emb.astype(np.float32).tobytes() for emb in image_features]

    def load_ai_models(self, need_ocr=True):
        print(f"Loading Models via ONNX Runtime...")
        
        # [關鍵修改] 放棄 open_clip，直接實例化我們的 Numpy 引擎
        preprocess = NumpyPreprocess(size=224)
        
        onnx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "onnx_clip", f"{self.model_name}_image.onnx")
        providers = ['DmlExecutionProvider', 'CPUExecutionProvider'] if (self.device == 'dml') else ['CPUExecutionProvider']
        
        image_session = ort.InferenceSession(onnx_path, providers=providers)
        ocr_engine = ONNXOCR(lang='ch', use_gpu=self.use_gpu_ocr) if need_ocr else None

        return image_session, preprocess, ocr_engine

    def update_folder_stats(self, conn):
        cursor = conn.cursor()
        cursor.execute("DELETE FROM model_stats WHERE model_name = ?", (self.model_name,))
        cursor.execute("""
            INSERT INTO model_stats (model_name, folder_path, image_count, last_scanned)
            SELECT e.model_name, f.folder_path, COUNT(f.id), datetime('now', 'localtime')
            FROM files f
            JOIN embeddings e ON f.id = e.file_id
            WHERE e.model_name = ?
            GROUP BY f.folder_path
        """, (self.model_name,))
        conn.commit()