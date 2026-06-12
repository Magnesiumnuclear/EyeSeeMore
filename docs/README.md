# EyeSeeMore 開發文檔索引

> 黃金法則：一份文件只回答一種核心問題；優先新增職責單一的 `.md`，不要先增加資料夾層級；README 只做導航與治理入口。
>
> 未來不論是人類還是 AI，新增或修改文件前，都必須先遵守 [DOCS_POLICY.md](./DOCS_POLICY.md) 的文件重整規則與撰寫公約。

> **EyeSeeMore** — CLIP 視覺向量 + OCR 文字 + FAISS 本地圖片語意搜尋器

本索引幫助開發者快速定位需要的技術文檔。所有文檔位於本文件夾內。

## 📖 快速導航

| 需求 | 閱讀文檔 | 內容 |
|------|---------|------|
| **了解專案架構與目錄結構** | [ARCHITECTURE.md](./ARCHITECTURE.md) | 各層職責、依賴關係、為什麼這樣組織 |
| **理解文件治理與撰寫公約** | [DOCS_POLICY.md](./DOCS_POLICY.md) | docs 重整規則、分類方式、黃金法則、AI 與人類共同遵守的文件公約 |
| **找出代碼應寫在哪層** | [LAYERS.md](./LAYERS.md) | core/ / ui/ / utils/ 的設計原則與示例 |
| **查 core 模組索引** | [MODULES_CORE.md](./MODULES_CORE.md) | core 模組的責任、閱讀時機、相關專題文入口 |
| **查 ui 模組索引** | [MODULES_UI.md](./MODULES_UI.md) | UI 模組、widget 與設定頁的索引與閱讀時機 |
| **掌握松散耦合與訊號設計** | [DESIGN_PATTERNS.md](./DESIGN_PATTERNS.md) | Thin Delegation / 依賴注入 / Signal / 跨執行緒 |
| **修改資料庫邏輯** | [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) | SQLite 完整 schema、WAL 模式、FAISS 向量化 |
| **完整理解背景索引引擎** | [INDEXER.md](./INDEXER.md) | indexer.py 的職責、三軌道流程、資料表互動、效能設計 |
| **理解模型加載與啟動時序** | [MODEL_LOADING.md](./MODEL_LOADING.md) | ModelProvider、非阻塞模型加載、Lazy Load OCR、啟動期間 UI 協調 |
| **查看已完成優化與量測** | [PERFORMANCE_NOTES.md](./PERFORMANCE_NOTES.md) | 已完成的效能優化、互動改善與設計取捨 |
| **執行效能測試與優化驗收** | [../benchmarks/README.md](../benchmarks/README.md) | benchmarks 套件用法、各腳本對應的問題與 PASS/FAIL 驗收 |
| **查看 OCR 推論引擎腳本** | [../onnx_ocr.py](../onnx_ocr.py) | ONNX PaddleOCR 推論入口，提供統一 `ocr()` 介面 |
| **查看 CLIP ONNX 轉換腳本** | [../export_clip_onnx.py](../export_clip_onnx.py) | 將 PyTorch CLIP 匯出為 ONNX 的開發工具腳本 |
| **新增功能的逐步指南** | [CONTRIBUTION.md](./CONTRIBUTION.md) | 從需求 → 設計 → 實裝 → i18n / QSS 規範 → 測試 |
| **多國語系 & 樣式表規範** | [CONTRIBUTION.md](./CONTRIBUTION.md#-ui-文字與樣式規範) | JSON 語言檔、QSS 集中管理、禁止 hardcode |
| **查看未來規劃與風險** | [ROADMAP.md](./ROADMAP.md) | 優先級、待處理議題、文件與程式面的下一階段規劃 |

## 🎯 常見問題速查

**Q: 我要新增一個功能，從哪開始？**
A: 先讀 [CONTRIBUTION.md](./CONTRIBUTION.md) 的「新增功能流程」章節。

**Q: 依賴注入老是報錯，為什麼？**
A: [DESIGN_PATTERNS.md](./DESIGN_PATTERNS.md) §3.2「Callable Provider 陷阱」有修復法。

**Q: 訊號連接總是 AttributeError，怎樣才安全？**
A: [DESIGN_PATTERNS.md](./DESIGN_PATTERNS.md) §3.3「訊號連接時序陷阱」有完整範例。

**Q: 我要改視窗狀態，但 setWindowFlag 會毀掉標題列？**
A: [DESIGN_PATTERNS.md](./DESIGN_PATTERNS.md) §3.5「Win32 整合注意事項」提供安全做法。

**Q: 我要改 indexer.py、掃描流程、OCR 補算或 embedding 寫入，先看哪份？**
A: 先讀 [INDEXER.md](./INDEXER.md)，再按需要補看 [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) 或 [MODULES_CORE.md](./MODULES_CORE.md)。

---

*最後更新：Phase 3-G 完工後。若有新增模組或架構調整，請同步更新相應文檔。*
