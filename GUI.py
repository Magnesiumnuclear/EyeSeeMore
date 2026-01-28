import os
import pickle
import threading
import time
import customtkinter as ctk
from PIL import Image, ImageTk
import torch
from transformers import CLIPProcessor, CLIPModel

# --- 全域設定 ---
INDEX_FILE = "image_embeddings_laion.pkl"
MODEL_NAME = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
IMAGE_ROOT = os.path.join(os.getcwd(), "data") 
THUMBNAIL_SIZE = (200, 200)
GRID_COLUMNS = 5 
# ----------------

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

class ImageSearchEngine:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_ready = False
        print(f"🚀 [Engine] Initializing on {self.device.upper()}...")
        
        try:
            self.model = CLIPModel.from_pretrained(MODEL_NAME).to(self.device)
            self.processor = CLIPProcessor.from_pretrained(MODEL_NAME)
            self.model.eval()

            if os.path.exists(INDEX_FILE):
                with open(INDEX_FILE, 'rb') as f:
                    data = pickle.load(f)
                self.stored_embeddings = data['embeddings'].to(self.device)
                self.stored_paths = data['paths']
                self.is_ready = True
                print(f"✅ [Engine] Loaded {len(self.stored_paths)} images into VRAM/RAM.")
            else:
                print(f"❌ [Engine] Index file not found: {INDEX_FILE}")
        
        except Exception as e:
            print(f"❌ [Engine] Error: {e}")

    def search(self, query, top_k=20):
        if not self.is_ready: return []
        
        with torch.no_grad():
            inputs = self.processor(text=[query], return_tensors="pt", padding=True).to(self.device)
            text_outputs = self.model.text_model(**inputs)
            text_features = self.model.text_projection(text_outputs.pooler_output)
            text_features /= text_features.norm(p=2, dim=-1, keepdim=True)

        similarity = (text_features @ self.stored_embeddings.T).squeeze(0)
        
        # 確保請求數量不超過總數
        k = min(top_k, len(self.stored_paths))
        values, indices = similarity.topk(k)

        results = []
        for i in range(k):
            idx = indices[i].item()
            results.append({
                "score": values[i].item(),
                "path": self.stored_paths[idx],
                "filename": os.path.basename(self.stored_paths[idx])
            })
        return results

class ResultCard(ctk.CTkFrame):
    def __init__(self, master, image_data, ctk_image):
        super().__init__(master, fg_color=("gray85", "gray17"), corner_radius=10)
        
        self.btn = ctk.CTkButton(
            self, 
            text="", 
            image=ctk_image, 
            fg_color="transparent", 
            hover_color=("gray70", "gray25"),
            command=lambda: self.open_file(image_data['path'])
        )
        self.btn.pack(padx=5, pady=(5, 0))

        fname = image_data['filename']
        if len(fname) > 15: fname = fname[:12] + "..."
        
        label_text = f"{fname}\nScore: {image_data['score']:.4f}"
        
        # 分數顏色：大於 0.3 顯示亮青色，否則一般顏色
        score_color = "cyan" if image_data['score'] > 0.3 else "gray70"
        
        self.label = ctk.CTkLabel(self, text=label_text, font=("Arial", 11), text_color=score_color)
        self.label.pack(padx=5, pady=(2, 5))

    def open_file(self, path):
        try:
            os.startfile(path)
        except Exception as e:
            print(f"Error opening file: {e}")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🔍 Semantic Image Search - RTX 4080 Pro")
        self.geometry("1200x800")
        
        self.img_cache = {} 
        self.engine = None

        self._setup_ui()
        threading.Thread(target=self._init_engine, daemon=True).start()

    def _setup_ui(self):
        # 1. 頂部控制列
        self.top_frame = ctk.CTkFrame(self, height=80, corner_radius=0)
        self.top_frame.pack(side="top", fill="x")

        # [新增] 數量限制區塊
        self.lbl_limit = ctk.CTkLabel(self.top_frame, text="Limit:", font=("Arial", 12, "bold"))
        self.lbl_limit.pack(side="left", padx=(20, 5))

        self.combo_limit = ctk.CTkComboBox(
            self.top_frame, 
            values=["20", "50", "100", "全部"],
            width=80,
            state="readonly" # 禁止亂打字
        )
        self.combo_limit.set("50") # 預設值
        self.combo_limit.pack(side="left", padx=5)

        # 搜尋輸入框
        self.entry = ctk.CTkEntry(
            self.top_frame, 
            placeholder_text="Enter tags (e.g., 'sorasaki hina, halo')...", 
            width=400, 
            height=40, 
            font=("Arial", 14)
        )
        self.entry.pack(side="left", padx=20, pady=20)
        self.entry.bind("<Return>", self._start_search)

        # 搜尋按鈕
        self.btn_search = ctk.CTkButton(self.top_frame, text="Search", command=self._start_search, width=100, height=40, font=("Arial", 14, "bold"))
        self.btn_search.pack(side="left", padx=10)

        # 進度條與狀態
        self.progress = ctk.CTkProgressBar(self.top_frame, width=200, mode="indeterminate")
        self.progress.pack(side="right", padx=20)
        self.progress.pack_forget()

        self.status_lbl = ctk.CTkLabel(self.top_frame, text="Loading Model...", text_color="orange")
        self.status_lbl.pack(side="right", padx=10)

        # 2. 結果顯示區
        self.scroll_frame = ctk.CTkScrollableFrame(self, corner_radius=0)
        self.scroll_frame.pack(side="bottom", fill="both", expand=True)
        
        for i in range(GRID_COLUMNS):
            self.scroll_frame.grid_columnconfigure(i, weight=1)

    def _init_engine(self):
        try:
            self.engine = ImageSearchEngine()
            self.after(0, lambda: self.status_lbl.configure(text="✅ System Ready", text_color="#2CC985"))
            self.after(0, lambda: self.btn_search.configure(state="normal"))
        except Exception as e:
            self.after(0, lambda: self.status_lbl.configure(text=f"❌ Error: {e}", text_color="red"))

    def _start_search(self, event=None):
        query = self.entry.get().strip()
        if not query or not self.engine: return

        # [新增] 讀取 Limit 值並判斷
        limit_str = self.combo_limit.get()
        if limit_str == "全部":
            target_k = len(self.engine.stored_paths) # 資料庫總數
            status_suffix = "(All)"
        else:
            target_k = int(limit_str)
            status_suffix = f"(Top {target_k})"

        # UI 鎖定
        self.btn_search.configure(state="disabled")
        self.progress.pack(side="right", padx=20)
        self.progress.start()
        self.status_lbl.configure(text=f"Searching {status_suffix}...", text_color="cyan")
        
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        # 將 target_k 傳入執行緒
        threading.Thread(target=self._run_search_thread, args=(query, target_k), daemon=True).start()

    def _run_search_thread(self, query, top_k):
        start_time = time.time()
        
        # 1. 取得搜尋結果 (使用動態 top_k)
        results = self.engine.search(query, top_k=top_k)

        # 2. 準備圖片 (快取機制)
        prepared_data = []
        for res in results:
            path = res['path']
            
            if path in self.img_cache:
                prepared_data.append((res, self.img_cache[path]))
            else:
                try:
                    with Image.open(path) as img:
                        img.load()
                        img = img.convert("RGB")
                        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                        
                        self.img_cache[path] = ctk_img
                        prepared_data.append((res, ctk_img))
                except Exception:
                    continue

        elapsed = time.time() - start_time
        self.after(0, lambda: self._update_ui_results(prepared_data, elapsed))

    def _update_ui_results(self, prepared_data, elapsed_time):
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_search.configure(state="normal")
        
        if not prepared_data:
            self.status_lbl.configure(text="No results found.", text_color="yellow")
            return

        self.status_lbl.configure(text=f"Found {len(prepared_data)} images ({elapsed_time:.2f}s)", text_color="#2CC985")

        for i, (data, ctk_img) in enumerate(prepared_data):
            row = i // GRID_COLUMNS
            col = i % GRID_COLUMNS
            
            card = ResultCard(self.scroll_frame, data, ctk_img)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

if __name__ == "__main__":
    app = App()
    app.mainloop()