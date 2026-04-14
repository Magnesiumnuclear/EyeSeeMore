# 🖼️ EyeSeeMore (Alpha)

[繁體中文] | [English]

**EyeSeeMore** 是一個小巧的實驗性本地圖片搜尋工具。
**EyeSeeMore** is a lightweight, experimental local image search tool.

當圖片收藏日益增加，而檔名往往是無意義的亂碼時，尋找特定圖片就成了一大難題。本專案的初衷是透過視覺模型讓電腦試著「理解」圖片內容，幫助使用者找回那些遺忘在角落的回憶。
As image collections grow and filenames are often meaningless random strings, finding a specific image becomes a challenge. The goal of this project is to use vision models to help the computer "understand" image content, helping users rediscover memories hidden in the corners of their storage.

> [!WARNING]
> 目前專案仍處於早期 **Alpha** 階段，許多功能尚在磨合與實驗中。
> This project is currently in the early **Alpha** stage; many features are still being refined and tested.

---

## ✨ 核心特色 | Key Features

* **不依賴檔名 (Filename Independent):** 嘗試透過視覺模型理解圖片內容，即便檔名完全沒有意義，也能透過描述文字進行檢索。
    Attempts to understand image content via vision models, allowing retrieval through text descriptions even if filenames are meaningless.
* **尊重隱私 (Privacy First):** 所有的運算、分析與儲存都在本地端完成，圖片絕對不會被上傳到任何雲端伺服器。
    All computation, analysis, and storage are performed locally; your images are never uploaded to any cloud server.
* **開箱即用 (Out-of-the-box):** 極力簡化安裝流程，透過 **DirectML** 技術，讓各類顯卡（AMD、Intel、NVIDIA）都能輕鬆執行 AI 搜尋，無需手動配置複雜的 CUDA 環境。
    Streamlined installation using **DirectML** technology, enabling AI search on various GPUs (AMD, Intel, NVIDIA) without complex CUDA configuration.

## 💡 使用情境 (Use Cases)

* **瞬時社群分享 (Instant Social Sharing):** 與朋友聊天時想發梗圖卻找不到？EyeSeeMore 旨在減少滑動尋找的流程，實現瞬間分享。
    Struggling to find a meme while chatting? EyeSeeMore aims to eliminate endless scrolling for instant sharing.
* **從截圖中尋找資訊 (Search from Screenshots):** 支援搜尋「錯誤代碼」或「會議記錄」，系統會透過 **OCR** 掃描圖片文字內容，精準定位重要截圖。
    Search for "Error Codes" or "Meeting Minutes." The system uses **OCR** to scan text within images, precisely locating important screenshots.
* **視覺筆記整理 (Visual Note Organizing):** 直接搜尋書本頁面或手寫筆記照片中的關鍵詞，快速找回所需資料。
    Search for keywords directly within photos of book pages or handwritten notes to retrieve information quickly.
* **無懼亂碼檔名 (No Fear of Messy Filenames):** 通訊軟體下載的隨機數字檔名不再是障礙，無需手動重命名也能輕鬆檢索。
    Randomly numbered filenames from messaging apps are no longer an obstacle; retrieve images easily without manual renaming.

## ⌨️ 快捷鍵與操控 | Shortcuts & Control

預覽模式提供類似遊戲的流暢巡覽體驗：
The preview mode provides a smooth, game-like navigation experience:

| 按鍵 (Key) | 功能說明 (Function) |
| :--- | :--- |
| `Space` | 快速開啟 / 關閉圖片預覽 (Toggle Image Preview) |
| `W` / `A` / `S` / `D` | 預覽模式下快速切換圖片 (Navigate images in preview mode) |
| `Shift` | 即時切換 OCR 紅框標記 (Toggle OCR bounding boxes) |

## 📝 如何啟用 OCR 文字辨識 | How to Enable OCR

EyeSeeMore 為了節省運算資源，預設不會對所有資料夾自動進行文字掃描。
To save resources, EyeSeeMore does not automatically scan all folders for text by default.

1.  點擊介面左下角的 **⚙️ 設定 (Settings)** 按鈕。
    Click the **⚙️ Settings** button at the bottom left.
2.  切換至 **📁 資料夾管理 (Folder Management)** 分頁。
    Switch to the **📁 Folder Management** tab.
3.  在目標資料夾項目上點擊 **右鍵 (Right Click)**。
    Right-click on the target folder.
4.  選擇 **「添加 XX OCR 標記」**（例如：添加中文 OCR 標記）。
    Select **"Add XX OCR Tag"** (e.g., Add Chinese OCR Tag).
5.  系統將會開始背景掃描，補全該資料夾圖片的文字資訊。
    The system will begin background scanning to index text information for images in that folder.

## 🛠️ 技術架構 | Tech Stack

本專案採用混合架構，兼顧執行效率與開發彈性：
This project uses a hybrid architecture for both performance and development flexibility:

* **後端邏輯 (Backend Logic):** 基於 **Python** 開發。
* **推理引擎 (Inference Engine):** 採用 **ONNX Runtime**，透過 **DirectML** 實現硬體加速 (DirectX 12)。
* **GUI & 啟動器 (GUI & Launcher):** 透過 **C++** 撰寫小巧的啟動器與安裝程式，確保環境與路徑依賴的完整性。
* **離線運行 (Offline Support):** 內建本地分詞資源 (**Tokenizer**)，確保在無網路環境下依然能正常啟動與搜尋。

## 🚀 未來願景與 Roadmap | Future Vision

### 近期目標 (Short-term Goals)
- [ ] 支援更強大的 CLIP 模型，實現「文字 + 圖片」複合式搜尋。
- [ ] 導入更強大的 OCR 模型，提供細部文字編輯功能。
- [ ] 實作軟體內的虛擬資料夾與自動分類系統。

### 終極目標：Android 自訂鍵盤 (Ultimate Goal: Android Custom Keyboard)
- [ ] 實作行動端 Web API 以支撐手機端需求。
- [ ] 開發 Android 鍵盤擴充功能：讓使用者在任何聊天軟體 (LINE, Discord 等) 中直接搜尋並貼上圖片。

## 📂 模型目錄結構 | Model Directory Structure

為了確保程式正常啟動與運行，請確保您的 `models/` 資料夾遵循以下路徑格式：
To ensure proper startup, please ensure your `models/` directory follows this structure:

```text
models/
├── onnx_clip/               # CLIP 語意搜尋模型 (CLIP Semantic Models)
│   ├── ViT-B-32_image.onnx
│   ├── ViT-B-32_text.onnx
│   └── ... 
├── tokenizers/              # 離線分詞資源 (Offline Tokenizers)
│   ├── openai-clip/         
│   └── xlm-roberta/         
└── ocr/                     # OCR 文字辨識模型包 (OCR Model Packs)
    ├── common/              # 通用偵測模型
    ├── ch/                  # 中文語言包
    └── ...
```

## 📥 下載指引 | Download Instructions
由於 AI 模型檔案較大 (6.43GB)，請從以下連結下載完整資源：
Due to the large size of AI models (6.43GB), please download full resources from the following links:

Main Setup: [EyeSeeMore_Setup.exe] (See Releases)

AI Models: ➡️ [Google Drive Link] (https://drive.google.com/drive/folders/1WT3Uckeo272F6_elHgWDT6scNOIGmldG?usp=drive_link)

Runtime & Assets: [Runtime.zip / App_Code.zip] (See Releases)

⚖️ 授權條款 | License
本專案遵循 GPLv3 (General Public License v3) 協議開發。
This project is developed under the GPLv3 license.

EyeSeeMore - 一個陪你一起找圖片的實驗性小助手。
EyeSeeMore - Your experimental assistant for finding images.

---

## 🏗️ 專案結構 | Project Architecture

```
rag-image/
├── main.py                     # 應用程式入口 (Entry Point)
├── Blur-main.py                # 主視窗 MainWindow 及所有 Widget
│
├── core/                       # 核心業務邏輯 (Business Logic)
│   ├── __init__.py
│   ├── paths.py                # 集中管理所有專案路徑常數
│   ├── config_manager.py       # 設定讀寫 (config.json / SQLite)
│   ├── search_orchestrator.py  # 搜尋執行緒調度與生命週期管理
│   └── image_action_manager.py # 圖片右鍵操作 (開啟/複製/重新命名)
│
├── ui/                         # 介面層 (UI Layer)
│   ├── __init__.py
│   ├── main_window_ui.py       # UI 版面配置 (setup_ui)
│   ├── action_handler.py       # EventFilter + 鍵盤/滑鼠動作處理
│   ├── navigation_manager.py   # 預覽模式的圖片切換邏輯
│   └── theme_manager.py        # 深色/淺色主題套用
│
├── utils/                      # 通用工具 (Utilities)
│   ├── __init__.py
│   └── translator.py           # i18n 多語言翻譯 (zh_TW / en_US)
│
├── indexer.py                  # 圖片索引服務 (IndexerService)
├── config_manager.py           # (已遷移至 core/ — 保留相容性)
├── theme_manager.py            # (已遷移至 ui/  — 保留相容性)
│
├── models/                     # AI 模型資源
│   ├── onnx_clip/              # CLIP ONNX 模型
│   ├── tokenizers/             # 離線分詞器
│   └── ocr/                    # OCR 語言包
│
├── languages/                  # 語系檔
│   ├── zh_TW.json
│   └── en_US.json
│
└── themes/                     # 主題檔
    ├── dark.json
    ├── light.json
    └── base_style.qss
```

### 模組職責說明 | Module Responsibilities

| 模組 | 職責 |
| :--- | :--- |
| `core/paths.py` | 單一路徑來源，所有子模組透過此檔取得 `BASE_DIR`、`MODELS_DIR` 等常數，避免路徑硬編碼 |
| `core/config_manager.py` | 讀寫 `config.json` 使用者設定，並管理 SQLite (`eyeseemore.db`) 索引資料庫 |
| `core/search_orchestrator.py` | 管理 `SearchWorker` QThread 的啟動、取消與結果派送；持有 `_retained` 防止 C++ 幽靈物件 |
| `core/image_action_manager.py` | 封裝右鍵選單所有圖片操作，透過 `toast_fn` callback 回報結果 |
| `ui/main_window_ui.py` | 純版面配置 (`setup_ui`)，不含任何業務邏輯 |
| `ui/action_handler.py` | 事件過濾器 (`eventFilter`) 及所有鍵盤/滑鼠快捷鍵處理 |
| `ui/navigation_manager.py` | 預覽模式的圖片前後切換，使用 callback 架構解耦 |
| `ui/theme_manager.py` | 讀取 `themes/*.json` 並套用 QSS 樣式表 |
| `utils/translator.py` | 解析 `languages/*.json`，提供 `t(section, key)` 翻譯函式 |

### 通訊模式 | Communication Patterns

* **Signals/Slots**: QThread Worker 完成後透過 PyQt6 signal 回傳結果至主執行緒
* **Callback**: `NavigationManager`、`ImageActionManager` 等模組透過建構子傳入 callback 函式，降低耦合
* **集中路徑**: 所有模組從 `core.paths` import 常數，變更路徑只需修改一處