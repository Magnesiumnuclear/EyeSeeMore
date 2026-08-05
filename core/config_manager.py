import os
import json
import copy
import time
import shutil
import tempfile
from core.paths import BASE_DIR, CONFIG_PATH, DB_PATH


# ==========================================
# [新增] 原子寫檔工具
#   一般的 open(path,'w') 會「先把檔案截斷成 0 位元組」再慢慢寫入，
#   中途當機／斷電就只剩半截 JSON，使用者設定直接報銷。
#   改成：同目錄暫存檔 → flush + fsync → os.replace 一次換名，
#   os.replace 在 Windows 與 POSIX 上都是原子操作，
#   因此磁碟上永遠只會看到「舊的完整檔」或「新的完整檔」。
#   （search_history_manager.py 也直接共用這支函式，避免重複實作）
# ==========================================
def atomic_write_json(path, data, indent=None):
    """把 data 以 JSON 原子寫入 path。寫入失敗時拋出例外，由呼叫端決定如何處理。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)

    # 暫存檔一定要跟目標同一個目錄（同一個檔案系統），os.replace 才保證原子性
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())   # 確保資料真的落到磁碟，而不是還躺在 OS 快取

        # Windows 上防毒／索引服務可能短暫鎖住檔案，換名失敗時重試幾次再放棄
        for attempt in range(3):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05)
    except Exception:
        # 只要沒走到 os.replace，原本的檔案就完全沒被動過；順手清掉暫存檔
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


class ConfigManager:
    def __init__(self):
        self.app_root = BASE_DIR
        self.config_path = CONFIG_PATH
        self.db_path = DB_PATH
        
        # ==========================================
        # [升級] 在這裡把所有我們最近新增的 UI 狀態都補上預設值
        # ==========================================
        self.default_config = {
            "source_folders": [],
            "model_name": "xlm-roberta-large-ViT-H-14",
            "pretrained": "frozen_laion5b_s13b_b90k",
            "search_limit": 50,
            "use_ocr": True,
            "use_gpu_ocr": False,
            "performance": {
                "indexing_batch_size":    4,     # 每批送 AI 的圖片數
                "db_commit_threshold":    24,    # 每幾張寫一次 DB
                "thumbnail_cache_size":   1000,  # 記憶體縮圖快取張數
                "thumbnail_thread_count": 8,     # 縮圖載入執行緒數
            },
            "ui_state": {
                "window_width": 1280,
                "window_height": 900,
                "is_maximized": False,
                "sidebar_expanded": True,
                "view_mode": "large",
                "precise_ocr_highlight": False,
                "margin_compensation": True,      # 邊緣縮減補償
                "ocr_deduplication": True,        # 多語系重疊防護
                "preview_wasd_mode": "nav",       # 空白鍵預覽 WASD 模式
                "ocr_shift_mode": "hold",         # Shift 鍵觸發邏輯
                "ocr_tag_mode": "anchored",        # OCR 懸浮標籤顯示方式
                "folders_accordion_open": False,   # 實體資料夾手風琴展開狀態
                "collections_accordion_open": False # 虛擬資料夾手風琴展開狀態
            }
        }
        self.config = self.load_config()

    def load_config(self):
        if not os.path.exists(self.config_path):
            # [修復] 必須深拷貝：直接沿用 default_config 會讓 self.config 與範本
            #        變成同一顆物件，之後 set() / add_source_folder() 會把預設值也一起改掉
            return self.save_config(copy.deepcopy(self.default_config))

        try:
            # [注意] 這裡只在 with 內做「讀取」，合併與回寫都移到區塊外；
            #        原子寫入的 os.replace 在 Windows 上無法覆蓋仍被開啟中的檔案
            with open(self.config_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)

            # 1. 淺層合併：補齊第一層缺失的 key
            #    （補進去的值一律深拷貝，避免 config 與 default_config 共用同一顆物件）
            for k, v in self.default_config.items():
                if k not in loaded:
                    loaded[k] = copy.deepcopy(v)

            # ==========================================
            # 2. [關鍵修復] 深層合併：確保 ui_state 裡面的新功能也會被強制寫入
            # ==========================================
            if "ui_state" in loaded:
                for sub_k, sub_v in self.default_config["ui_state"].items():
                    if sub_k not in loaded["ui_state"]:
                        loaded["ui_state"][sub_k] = copy.deepcopy(sub_v)

            if "performance" not in loaded:
                loaded["performance"] = copy.deepcopy(self.default_config["performance"])
            else:
                for sub_k, sub_v in self.default_config["performance"].items():
                    if sub_k not in loaded["performance"]:
                        loaded["performance"][sub_k] = copy.deepcopy(sub_v)

            # 3. [升級] 將舊的 use_ocr (布林值) 無縫轉移為 enabled_langs (陣列)
            new_folders = []
            for item in loaded.get("source_folders", []):
                if isinstance(item, str):
                    langs = ["ch"] if loaded.get("use_ocr", True) else []
                    new_folders.append({"path": item, "icon": "", "enabled_langs": langs})
                else:
                    if "enabled_langs" not in item:
                        langs = ["ch"] if item.get("use_ocr", loaded.get("use_ocr", True)) else []
                        item["enabled_langs"] = langs
                    new_folders.append(item)
            loaded["source_folders"] = new_folders

            # 4. 讀取完畢後，強制回寫一次，讓剛補齊的預設值實體化儲存到 config.json 裡！
            self.save_config(loaded)

            return loaded
        except Exception as e:
            print(f"[Config] Load error: {e}")
            # ==========================================
            # [修復] 解析失敗時「先備份再退回預設值」
            #   否則下一次 set() / add_source_folder() 就會把壞掉的 config.json
            #   用預設值蓋掉，使用者的 source_folders / ui_state 永久救不回來
            # ==========================================
            self._backup_corrupt_config()
            return copy.deepcopy(self.default_config)

    def _backup_corrupt_config(self):
        """[新增] 把無法解析的 config.json 另存一份 .corrupt 副本，保留人工救援的機會。"""
        try:
            if not os.path.exists(self.config_path):
                return
            backup_path = self.config_path + ".corrupt"
            if os.path.exists(backup_path):
                # 已經有舊備份就加時間戳，不要把上一次的殘骸蓋掉
                backup_path = f"{backup_path}.{time.strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(self.config_path, backup_path)
            print(f"[Config] 設定檔損毀，已備份至：{backup_path}")
        except Exception as e:
            print(f"[Config] Backup corrupt config error: {e}")

    def save_config(self, config_data=None):
        if config_data: self.config = config_data
        try:
            # [修復] 改用原子寫入，寫到一半被中斷也不會留下半截的 config.json
            atomic_write_json(self.config_path, self.config, indent=4)
            return self.config
        except Exception as e:
            print(f"[Config] Save error: {e}")
            return self.config

    def get(self, key, default=None):
        return self.config.get(key, self.default_config.get(key))

    def set(self, key, value):
        self.config[key] = value
        self.save_config()

    def add_source_folder(self, folder_path):
        folder_path = os.path.normpath(folder_path)
        current = self.config.get("source_folders", [])
        
        # 檢查是否已經存在相同的資料夾
        if any(os.path.normpath(f["path"]) == folder_path for f in current):
            return False
            
        
        current.append({
            "path": folder_path, 
            "icon": "", 
            "enabled_langs": []
        })
        
        self.set("source_folders", current)
        return True

    # [新增] 用於動態切換單一資料夾的特定語系標記
    def toggle_folder_lang(self, folder_path, lang_code):
        folder_path = os.path.normpath(folder_path)
        for f in self.config.get("source_folders", []):
            if os.path.normpath(f["path"]) == folder_path:
                langs = f.get("enabled_langs", [])
                if lang_code in langs:
                    langs.remove(lang_code) # 已存在則移除
                else:
                    langs.append(lang_code) # 不存在則加入
                
                # 簡單排序一下讓 UI 顯示更整齊：中文 -> 日文 -> 韓文
                sort_order = {"ch": 1, "jp": 2, "kr": 3}
                f["enabled_langs"] = sorted(langs, key=lambda x: sort_order.get(x, 99))
                break
        self.save_config()

    def remove_source_folder(self, folder_path):
        folder_path = os.path.normpath(folder_path)
        current = self.config.get("source_folders", [])
        new_list = [f for f in current if os.path.normpath(f["path"]) != folder_path]
        self.set("source_folders", new_list)

    def update_folder_icon(self, folder_path, new_icon):
        folder_path = os.path.normpath(folder_path)
        for f in self.config.get("source_folders", []):
            if os.path.normpath(f["path"]) == folder_path:
                f["icon"] = new_icon
                break
        self.save_config()

    def update_folder_order(self, ordered_paths):
        """根據傳入的路徑陣列，重新排序 config 內的資料夾"""
        current = self.config.get("source_folders", [])
        lookup = {os.path.normpath(f["path"]): f for f in current}
        
        new_list = []
        for path in ordered_paths:
            norm_path = os.path.normpath(path)
            if norm_path in lookup:
                new_list.append(lookup[norm_path])
        self.set("source_folders", new_list)