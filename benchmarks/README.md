# benchmarks/ — 效能測試套件

> 用途：以可重複的量測證明效能優化「真的有效」。
> 每個腳本對應效能分析報告中的一項發現，並內建「優化完成」的驗收檢查。
> 所有腳本只在暫存目錄建合成資料，**絕不寫入真實 `images.db` 與圖片**。

## 快速開始

```powershell
# 於 benchmarks/ 目錄下，使用專案的 Python 環境
cd benchmarks

# 1. 優化前先建立基準
python run_all.py --label baseline

# 2. 套用優化後重跑
python run_all.py --label optimized

# 3. 逐項對照（自動取最新兩份結果）
python compare.py --latest db_indexes
python compare.py --latest search_hotpath
python compare.py --latest thumbnail_cache
python compare.py --latest startup_imports
```

執行較慢時可加 `--quick` 縮小資料規模（趨勢不變）。

## 腳本對照表

| 腳本 | 驗證的問題 | 優化內容 | 驗收標準 |
|------|-----------|---------|---------|
| `bench_db_indexes.py` | **P0-2** `init_db()` 零二級索引：級聯刪除、軌道 C 批查、OCR JOIN 全表掃描 | 在 `indexer.init_db()` 加入 `idx_ocr_file_id` / `idx_files_folder`（實測 `idx_emb_model` 有害，不建議） | `--check-real` 回報兩個索引皆 PASS；合成 DB 上有索引版顯著快於無索引版 |
| `bench_search_hotpath.py` | **P1-4** FAISS 每次啟動重建（HNSW 建構分鐘級）；**P1-5** 每次搜尋 O(N) normpath 與文字掃描 | `faiss.write_index()` 持久化 + 啟動時 `read_index()`；`load_data_from_db` 預快取 `norm_path` | `read_index` 遠快於 `hnsw_build`；cached 過濾遠快於 normpath 過濾 |
| `bench_thumbnail_cache.py` | **P0-1** L2 快取路徑分裂：indexer 寫 `<root>/.cache`，UI 讀 `ui/widgets/.cache`，54k 張預產縮圖全被浪費 | 兩端統一從 `core/paths.py` 取得快取路徑；遷移/清除 `ui/widgets/.cache` | `--check-dirs` 回報 PASS（UI 端目錄不存在或為空）；快取命中比未命中快一個數量級 |
| `bench_startup_imports.py` | **P0-3** 主檔頂層 import 過重（`transformers`、`faiss` 未使用仍被 import；`indexer` 連帶拉入 cv2/onnxruntime） | 刪除未使用的頂層 import、延後重模組到實際使用點 | `blur_main_top_level_imports` 指標明顯下降（腳本以 AST 讀取主檔實際 import 清單，改完即生效） |

## 向量建立量測（profiling 工具，非回歸守門）

`bench_vectorize.py` 是**剖析型** benchmark，用來在優化 CLIP 向量建立路徑前後做對照（尚未實作優化）。
與上表不同，它不是 PASS/FAIL 守門，而是量出瓶頸分佈：

- 印出 image encoder 的輸入 shape → 判斷是否**動態 batch 軸**（調大 batch 的前提）。
- 各 batch size 的 `session.run` 吞吐（張/秒、ms/張）。
- `NumpyPreprocess` 與「解碼+轉正+RGB+前處理」的單張 CPU 成本。
- CPU 階段 vs GPU 推論的對比 → 量出 CPU/GPU 管線化可省的上限。

需要真實 `models/onnx_clip/{model}_image.onnx`（找不到則只量前處理）。因相依模型 + GPU
且耗時較長，**刻意不納入 `run_all.py`**，作為針對性工具單獨執行：

```powershell
python bench_vectorize.py --inspect                 # 只印輸入 shape / providers
python bench_vectorize.py --label baseline          # 完整量測,存基準
python bench_vectorize.py --batches 1,4,8,16,32 --repeat 8
# 優化 indexer 後:
python bench_vectorize.py --label optimized
python compare.py --latest vectorize
```

> 量測結論摘要請見 PERFORMANCE_NOTES.md Phase 3-H（向量建立段）；數據隨機器/GPU 而異，
> 跨 label 比較務必在同一台機器。

## 單獨執行與驗收檢查

```powershell
# 只檢查真實 DB 是否已建立建議索引（唯讀，不量測）
python bench_db_indexes.py --check-real

# 只檢查縮圖快取目錄是否仍分裂
python bench_thumbnail_cache.py --check-dirs

# 自訂規模
python bench_db_indexes.py --files 50000 --label baseline
python bench_search_hotpath.py --items 100000 --dim 1024
```

## 結果檔案

每次執行寫入 `results/{bench}_{label}_{timestamp}.json`，內含：

- `metrics`：各指標的 min / mean / median / max（秒）
- `sysinfo`：平台、Python 版本，以及 **`git_commit`**（產生報告時的程式碼版本）
- `extra`：資料規模、驗收檢查結果等附帶資訊

`compare.py` 以 **median** 為準計算倍率；±30% 內視為雜訊，不標記。

### Git 版本追蹤（效能回溯）

每份報告的 `sysinfo.git_commit` 會自動填入產生當下 `git rev-parse --short HEAD`
的結果（由 `bench_common.get_git_commit_hash()` 取得；非 git 環境或取得失敗時
為 `"unknown"`，不影響量測）。這讓每筆效能數據都精準綁定一個程式碼版本，用途：

- **追蹤效能退化**：發現某指標變慢時，可直接比對兩份報告的 `git_commit`，
  鎖定是哪段期間的變更造成退化。
- **支援 `git bisect`**：對可疑區間逐一 checkout commit、重跑同一 bench，
  以 JSON 內的 `git_commit` 對照，二分搜尋出引入退化的那個 commit。
- **跨機器/長期比較的可信度**：數據不再是「某次跑出來的」，而是「某個版本在某台機器上的」。

> 建議：要保留為基準的報告，commit 後再跑（確保 `git_commit` 指向乾淨版本，
> 而非含未提交變更的工作狀態）。

## 注意事項

1. 量測請盡量在機器空閒時進行，背景索引或其他重負載會污染數字。
2. `bench_search_hotpath.py` 預設 50,000 筆 × 1024 維，HNSW 建構需要一段時間
   （這正是要量測的啟動成本）；趕時間用 `--quick`。
3. `bench_startup_imports.py` 每個模組都在全新子行程量測（冷 import），
   受磁碟快取影響，第一次執行的數字最接近真實冷啟動。
4. 跨 label 比較必須在同一台機器、同一個 Python 環境下進行。
