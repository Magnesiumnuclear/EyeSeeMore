# MODULES_UI.md — ui 模組索引

> 這份文件只回答：ui 層有哪些模組、各自負責什麼、什麼時候應該去讀或修改它。
> 不涵蓋完整互動流程與所有 widget 細節；若要看分層邊界請讀 LAYERS.md，若要看 Win32 視窗整合請改讀後續專題文 WINDOW_INTEGRATION.md。

---

## 如何使用這份索引

1. 先確認問題屬於 UI 組裝、事件轉發、視圖控制或設定頁。
2. 用下表定位可能的模組。
3. 若問題跨到搜尋、索引、OCR 或模型生命週期，應回頭搭配 `MODULES_CORE.md` 或專題文一起看。

---

## 主布局與控制器

| 模組 | 主要責任 | 何時應該讀它 | 相關文件 |
|------|----------|--------------|----------|
| `main_window_ui.py` | MainWindow 視覺元件佈局 | 調整主畫面結構、元件配置、初始化前提 | `ARCHITECTURE.md` |
| `action_handler.py` | 鍵盤與滑鼠事件分發 | 快捷鍵、預覽操作、滑鼠中鍵等行為 | `DESIGN_PATTERNS.md` |
| `gallery_view_controller.py` | 畫廊視圖狀態、過濾、排序與顯示 | 搜尋結果顯示、視圖模式、診斷狀態 | `INDEXER.md` |
| `window_state_manager.py` | 視窗狀態、置頂與標題列座標同步 | 最大化、置頂、DPR、標題列互動 | 後續建議拆到 `WINDOW_INTEGRATION.md` |

---

## 原有管理器與面板

| 模組 | 主要責任 | 何時應該讀它 | 相關文件 |
|------|----------|--------------|----------|
| `theme_manager.py` | 主題讀取、變數替換與套用 | 主題切換、QSS 套用、顏色變數 | `CONTRIBUTION.md` |
| `navigation_manager.py` | 上一頁 / 下一頁狀態堆疊 | 導航返回、捲動位置恢復 | `ARCHITECTURE.md` |
| `inspector_panel.py` | 過濾、屬性與 OCR 三分頁 | 權重、limit、屬性顯示與 OCR 面板 | `INDEXER.md` |

---

## Phase 3-F 拆出的主要模組

| 模組 | 主要責任 | 何時應該讀它 | 相關文件 |
|------|----------|--------------|----------|
| `gallery_model.py` | 搜尋結果 model 與 list view | model reset、排序、縮圖清單顯示 | `PERFORMANCE_NOTES.md` |
| `preview_overlay.py` | 全螢幕預覽與 OCR 互動 | 預覽層、鍵盤導覽、OCR 框顯示 | 後續建議拆到 `OCR_FLOW.md` |
| `settings_dialog.py` | 設定對話框與 onboarding | 設定入口、分頁組裝、跨頁 hub | `CONTRIBUTION.md` |
| `sidebar_widget.py` | 側邊欄與 hover 選單 | 資料夾清單、集合區、統計顯示 | `ARCHITECTURE.md` |

---

## 原子 widget 與繪製元件

| 模組 | 主要責任 | 何時應該讀它 | 相關文件 |
|------|----------|--------------|----------|
| `widgets/base.py` | widget 基類與統一錯誤協議 | 新增共用 widget 基礎能力 | `CONTRIBUTION.md` |
| `widgets/drag_list.py` | 拖曳列表與鬼影效果 | 重排 UI、拖曳視覺效果 | `DESIGN_PATTERNS.md` |
| `widgets/elided_label.py` | 可省略長文字的 QLabel | TopBar、狀態列、可縮放文字元件 | `PERFORMANCE_NOTES.md` |
| `widgets/search_capsule.py` | 搜尋膠囊、OCR 切換與歷史下拉 | 搜尋輸入體驗、歷史操作 | `CONTRIBUTION.md` |
| `widgets/empty_state.py` | 空狀態覆蓋層 | 無結果或空資料夾視覺提示 | `gallery_view_controller.py` |
| `widgets/feature_widgets.py` | 特徵標籤面板 | 多模態特徵顯示、標籤 UI | `preview_overlay.py` |
| `widgets/image_delegate.py` | 畫廊卡片繪製與縮圖代理 | paint、卡片渲染與縮圖策略 | `PERFORMANCE_NOTES.md` |
| `widgets/ocr_widgets.py` | OCR 框選、標籤與互動 | OCR 標註、框選、裁切互動 | 後續建議拆到 `OCR_FLOW.md` |

---

## 設定頁面群組

所有 `ui/settings_pages/*.py` 都遵守同一個原則：

1. 透過 `ctx` 字典注入依賴。
2. 不持有 `main_window` 參照。
3. 只處理頁面 UI 與設定互動，不直接實作核心流程。

### 常見頁面

| 頁面 | 主要責任 |
|------|----------|
| `folders_page.py` | 資料夾管理與排序 |
| `ai_engine_page.py` | 模型與 OCR 設定 |
| `appearance_page.py` | 主題與視圖設定 |
| `hotkeys_page.py` | 快捷鍵管理 |
| `performance_page.py` | 快取與效能相關選項 |
| `auto_tasks_page.py` | 自動任務與掃描策略 |
| `language_page.py` | 語言切換 |
| `about_page.py` | 版本與說明 |

---

## 快速判斷規則

### 先看 `ui/` 模組索引的情況

1. 問題直接涉及 widget、佈局、快捷鍵、面板或視圖顯示。
2. 修改需要直接持有或操作 widget。
3. 你正在處理 MainWindow 周邊的組裝與互動。

### 應切回其他文件的情況

1. 你正在追搜尋、索引或模型加載的完整鏈路。
2. 問題其實是資料邏輯，不是顯示邏輯。
3. 你需要的是設計模式與分層規則，而不是檔名導覽。

---

## 文件維護規則

1. 這份文件是 UI 索引，不是所有 UI 實作的完整規格書。
2. 若某個 UI 主題跨越多模組，應拆成流程文，而不是把內容塞回這裡。
3. 若新增大型 UI 模組，補一列索引即可；只有在需要完整設計背景時才新增專題文。
