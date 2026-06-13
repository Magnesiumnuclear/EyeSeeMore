# CONTRIBUTION.md — 開發流程、整合規範與提交要求

> 這份文件只回答：在 EyeSeeMore 中新增或修改功能時，應該怎麼規劃、落點、驗證與同步文檔。
> 不涵蓋完整架構背景或所有模組細節；若要看分層規則，請讀 LAYERS.md；若要看常見模式與陷阱，請讀 DESIGN_PATTERNS.md。

---

## 閱讀順序

接到任務後，先依下面順序建立上下文：

1. `README.md`：找到對應主題文件。
2. `ARCHITECTURE.md`：理解整體組裝方式。
3. `LAYERS.md`：判斷新代碼該落在哪一層。
4. `DESIGN_PATTERNS.md`：確認依賴注入、訊號與 Win32 等模式。
5. 功能專題文：例如 `INDEXER.md`、`MODEL_LOADING.md`、`DATABASE_SCHEMA.md`。
6. 模組索引文：`MODULES_CORE.md`、`MODULES_UI.md`。

---

## 標準修改流程

### 1. 先判斷責任邊界

修改前先回答三件事：

1. 這是結構問題、功能流程問題，還是單一模組問題。
2. 這段代碼應該落在 `core/`、`ui/`、`ui/widgets/`、`ui/settings_pages/` 還是 `utils/`。
3. 這次修改是否會影響跨執行緒、資料一致性或原生 Win32 行為。

### 2. 再設計依賴方式

優先順序如下：

1. 建構子注入：依賴在建立時就已就緒。
2. 延遲注入：依賴會稍後建立。
3. Callable Provider：依賴可能 rebinding，需要永遠取得最新參照。

若不確定，先回頭看 `DESIGN_PATTERNS.md` 對應章節，不要自行發明第四種模式。

### 3. 明確定義訊號邊界

1. 純資料邏輯不必發訊號。
2. 需要通知多個 UI 元件時，由 `core/` 發訊號。
3. 涉及背景執行緒回主執行緒時，用 Qt 訊號橋接。
4. 不要讓 `core/` 直接持有或操作 widget。

### 4. 保留 MainWindow 的薄委派層

若外部呼叫端已經習慣透過 MainWindow 使用功能，優先保留公開入口，再委派到新模組，而不是把所有呼叫點都改掉。

### 5. 做最窄驗證

每次修改後，至少做一種最貼近修改範圍的驗證：

1. 單檔語法檢查。
2. 窄範圍 import 檢查。
3. UI smoke test。
4. 功能操作的最小手動驗證。
5. 自動化回歸測試（見 [tests/README.md](../tests/README.md)）。
6. 效能量測與優化驗收（見 [benchmarks/README.md](../benchmarks/README.md)）。

### 6. 同步更新文檔

若修改影響的是規則、流程或入口，請同步更新唯一真理源與索引文。

---

## 落點速查

### 放在 `core/`

1. 純資料邏輯。
2. 資料庫 CRUD。
3. 模型、索引、搜尋、進度控制。
4. 不直接碰 widget 的 QObject 控制器。

### 放在 `ui/`

1. 視圖控制器。
2. 佈局與事件轉發。
3. 直接持有 widget 的組裝邏輯。

### 放在 `ui/widgets/`

1. 可複用原子 widget。
2. 單一元件的繪製與局部互動。

### 放在 `ui/settings_pages/`

1. 設定對話框分頁。
2. 透過 `ctx` 字典注入依賴的 UI。

### 放在 `utils/`

1. 跨層工具函式。
2. 不依賴 PyQt 與業務模組的純工具。

---

## UI 文字與樣式規範

### i18n 規則

1. 所有 UI 文字都應放在 `languages/*.json`。
2. 代碼中透過 `Translator.t()` 取值，不直接 hardcode 介面字串。
3. 新增 key 時，至少同步更新 `zh_TW.json` 與 `en_US.json`。

### QSS 規則

1. 共用樣式集中在 `themes/base_style.qss`。
2. 顏色變數集中在 `themes/*.json`。
3. Python 端優先設 `objectName`，不要在各處直接寫 `setStyleSheet()`。
4. 只有主題切換這種全域入口，才允許統一載入整份 QSS。

### UI 修改前檢查

1. 是否新增了未進語言檔的字串。
2. 是否用了新的 `objectName` 卻忘了補 QSS。
3. 是否把樣式寫回 Python 內聯。

---

## 文件同步規則

### 何時必須更新文檔

1. 新增重要模組或子系統。
2. 改變分層規則、依賴方式或訊號邊界。
3. 改變搜尋、索引、OCR、模型加載或 Win32 流程。
4. 改變設定欄位、資料表或遷移策略。

### 更新順序

1. 先更新唯一真理源。
2. 再更新 `README.md` 的入口。
3. 最後更新索引文與 roadmap 摘要。

### 對應關係

1. 分層規則：`LAYERS.md`
2. 設計模式：`DESIGN_PATTERNS.md`
3. 文件治理：`DOCS_POLICY.md`
4. 未來規劃：`ROADMAP.md`
5. 已完成優化：`PERFORMANCE_NOTES.md`

---

## 提交前檢查清單

- [ ] 修改落點符合分層規則。
- [ ] 沒有讓 `core/` 直接碰 widget。
- [ ] 訊號與執行緒邊界清楚。
- [ ] 新字串已進語言檔。
- [ ] 新樣式已進 QSS 或主題變數。
- [ ] 至少做過一種最窄驗證（必要時執行自動化測試，見 tests/README.md）。
- [ ] 需要時已同步更新 docs。

---

## 文件維護規則

1. 這份文件只保留開發流程、整合規範與提交要求。
2. 若內容開始膨脹成架構教科書，應回流到 `ARCHITECTURE.md` 或 `LAYERS.md`。
3. 若內容開始膨脹成模組百科，應回流到 `MODULES_CORE.md`、`MODULES_UI.md` 或專題文。
