# EyeSeeMore 開發文檔索引

> **EyeSeeMore** — CLIP 視覺向量 + OCR 文字 + FAISS 本地圖片語意搜尋器

本索引幫助開發者快速定位需要的技術文檔。所有文檔位於本文件夾內。

## 📖 快速導航

| 需求 | 閱讀文檔 | 內容 |
|------|---------|------|
| **了解專案架構與目錄結構** | [ARCHITECTURE.md](./ARCHITECTURE.md) | 各層職責、依賴關係、為什麼這樣組織 |
| **找出代碼應寫在哪層** | [LAYERS.md](./LAYERS.md) | core/ / ui/ / utils/ 的設計原則與示例 |
| **理解核心模組（8 個）** | [MODULES_CORE.md](./MODULES_CORE.md) | PinManager / OcrRepository / Collection / ETA / 等詳解 |
| **學習 UI 控制器與 widget** | [MODULES_UI.md](./MODULES_UI.md) | GalleryViewController / WindowStateManager / 設定頁面 |
| **掌握松散耦合與訊號設計** | [DESIGN_PATTERNS.md](./DESIGN_PATTERNS.md) | Thin Delegation / 依賴注入 / Signal / 跨執行緒 |
| **修改資料庫邏輯** | [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) | SQLite 完整 schema、WAL 模式、FAISS 向量化 |
| **完整理解背景索引引擎** | [INDEXER.md](./INDEXER.md) | indexer.py 的職責、三軌道流程、資料表互動、效能設計 |
| **新增功能的逐步指南** | [CONTRIBUTION.md](./CONTRIBUTION.md) | 從需求 → 設計 → 實裝 → i18n / QSS 規範 → 測試 |
| **多國語系 & 樣式表規範** | [CONTRIBUTION.md](./CONTRIBUTION.md#-ui-文字與樣式規範) | JSON 語言檔、QSS 集中管理、禁止 hardcode |
| **查看重構進度與願景** | [ROADMAP.md](./ROADMAP.md) | Phase 1-2 戰績、Phase 3+ 規劃、既知 Bug |

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

*最後更新：Phase 2 完工後。若有新增模組或架構調整，請同步更新相應文檔。*
