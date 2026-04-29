# EyeSeeMore — 自定義標題列與釘選功能 功能設計書

> **狀態**：設計討論中，尚未實作  
> **平台**：僅限 Windows（Win32 API）  
> **版本目標**：Post-Alpha

---

## 1. 功能目標

### 1.1 核心需求

| 功能 | 說明 |
|------|------|
| **視窗置頂（Always on Top）** | 一鍵讓 EyeSeeMore 浮在所有視窗之上，方便在 Discord、Photoshop 等軟體旁邊同時操作 |
| **自定義標題列** | 取代 Windows 原生標題列，讓控制按鈕與主題配色完全統一 |
| **Windows 11 Snap Layouts** | 懸停自定義最大化按鈕時，彈出 Windows 11 原生分屏選單 |
| **原生縮放手感** | 拖動邊框縮放視窗時，動畫與手感與系統原生相同 |

### 1.2 使用場景

使用者在 Discord 貼圖時，需要一邊看著 EyeSeeMore 找圖，一邊將結果拖拽（Drag & Drop）至 Discord 視窗。  
**釘選（常駐最上層）** 消除了 Alt+Tab 切換的摩擦，讓搜尋→拖拽流程一氣呵成。

---

## 2. 技術棧

```
┌─────────────────────────────────────────────────────┐
│  UI / 業務邏輯層     Python 3.10+ / PyQt6           │
│  (搜尋、OCR、主題、DB、狀態管理)                    │
├─────────────────────────────────────────────────────┤
│  橋接層              ctypes（Python 內建）           │
│  (HWND 傳遞、按鈕座標地圖、DLL 載入)               │
├─────────────────────────────────────────────────────┤
│  視窗原生控制層      C++ / Win32 API (.dll)         │
│  (WM_NCHITTEST 攔截、Snap Layouts、縮放動畫)        │
├─────────────────────────────────────────────────────┤
│  開發工具            Visual Studio (MSVC) + CMake   │
└─────────────────────────────────────────────────────┘
```

| 層級 | 負責任務 | 不負責 |
|------|----------|--------|
| Python / PyQt6 | 所有 UI 繪製、按鈕座標回報、狀態持久化 | Win32 訊息迴圈細節 |
| ctypes 橋接 | HWND 移交、座標更新、DLL 生命週期 | 直接操作 WndProc |
| C++ DLL | WM_NCHITTEST 攔截、HTMAXBUTTON 回傳、縮放邏輯 | UI 繪製 |

---

## 3. UI 設計

### 3.1 TopBar 佈局變更

**現有佈局（`ui/main_window_ui.py`）：**
```
← →  [Breadcrumb]  ‹──stretch──›  [SearchCapsule]  ‹──stretch──›  [StatusText] [📊]
```

**目標佈局（自定義標題列模式）：**
```
← →  [Breadcrumb]  ‹──stretch──›  [SearchCapsule]  ‹──stretch──›  [StatusText] [📊] [📌] [─] [□] [✕]
```

新增元件說明：

| 元件 | ObjectName | 類型 | 說明 |
|------|-----------|------|------|
| 釘選按鈕 | `PinBtn` | `QPushButton` (checkable) | 切換 Always on Top |
| 最小化按鈕 | `WinMinBtn` | `QPushButton` | 呼叫 `showMinimized()` |
| 最大化/還原 | `WinMaxBtn` | `QPushButton` (checkable) | `showMaximized()` / `showNormal()` |
| 關閉按鈕 | `WinCloseBtn` | `QPushButton` | `close()` |

### 3.2 釘選按鈕視覺狀態

```
未釘選                    釘選中
━━━━━━━━                 ━━━━━━━━━━━━━━━━━━━━━━━━━
圖示：📌（灰色/半透明）   圖示：📌（主題色，旋轉 45°）
背景：透明               背景：theme.primary 色（低透明度）
Tooltip：「釘選視窗至最上層」  Tooltip：「取消釘選」
```

**邊框特效（釘選中）：**  
利用 `QGraphicsDropShadowEffect` 在 `MainWindow` 外圍加上極細（1px）的主題色發光邊框，  
讓視窗視覺上真正「浮」在螢幕上。

### 3.3 快捷鍵

| 快捷鍵 | 動作 |
|--------|------|
| `Ctrl + T` | 切換視窗置頂狀態 |

---

## 4. C++ DLL 規格（`EyeSeeMoreWin.dll`）

### 4.1 存放位置
```
src_cpp/
└── win_titlebar/
    ├── CMakeLists.txt
    ├── titlebar_hook.h     ← 對 Python ctypes 公開的 C 介面
    └── titlebar_hook.cpp   ← 實作
```

### 4.2 公開介面（C ABI）

```c
// 安裝視窗掛鉤，傳入 PyQt6 視窗的 HWND
// 回傳 0 = 成功，非 0 = 錯誤碼
extern "C" __declspec(dllexport)
int ESM_InstallHook(HWND hwnd);

// 更新按鈕感應區域座標（視窗尺寸改變時由 Python 呼叫）
// 座標為相對於視窗左上角的客戶端座標
extern "C" __declspec(dllexport)
void ESM_SetButtonRects(
    RECT pin_rect,    // 釘選按鈕區域
    RECT max_rect,    // 最大化按鈕區域（觸發 Snap Layouts）
    RECT min_rect,    // 最小化按鈕區域
    RECT close_rect   // 關閉按鈕區域
);

// 移除掛鉤，還原原始 WndProc（程式關閉時呼叫）
extern "C" __declspec(dllexport)
void ESM_UninstallHook(HWND hwnd);
```

### 4.3 WM_NCHITTEST 回傳值對照表

| 滑鼠位置 | 回傳值 | Windows 行為 |
|---------|--------|-------------|
| 標題列空白區 | `HTCAPTION` | 允許拖動視窗 |
| 最大化按鈕 | `HTMAXBUTTON` | **觸發 Snap Layouts 選單** |
| 最小化按鈕 | `HTMINBUTTON` | 標準最小化提示 |
| 關閉按鈕 | `HTCLOSE` | 標準關閉提示 |
| 左邊框 | `HTLEFT` | Windows 接管縮放動畫 |
| 右邊框 | `HTRIGHT` | Windows 接管縮放動畫 |
| 上邊框 | `HTTOP` | Windows 接管縮放動畫 |
| 下邊框 | `HTBOTTOM` | Windows 接管縮放動畫 |
| 四個角 | `HTTOPLEFT` 等 | Windows 接管斜向縮放 |
| 其他客戶區 | `HTCLIENT` | 正常 PyQt6 事件 |

### 4.4 WM_NCCALCSIZE 處理
回傳 `0` 給 `WM_NCCALCSIZE(wParam=1)`，告訴 Windows「不要繪製系統標題列」，  
但保留視窗陰影（`DWM_WINDOW_CORNER_PREFERENCE`）。

---

## 5. Python 端實作規格

### 5.1 新增 `core/win_titlebar.py`（橋接模組）

```python
# 職責：
# 1. 載入 EyeSeeMoreWin.dll（透過 ctypes）
# 2. 提供 install_hook(hwnd) / update_rects(...) / uninstall_hook(hwnd) 三個函式
# 3. 在 DLL 不存在時（開發環境）降級為 no-op，保持程式可執行
```

### 5.2 `MainWindow` 初始化流程

```
1. __init__() 呼叫 init_ui()
2. init_ui() 建立自定義 TopBar（含四個控制按鈕）
3. 設定 Qt.WindowType.FramelessWindowHint
4. 視窗 show() 完成後，呼叫 win_titlebar.install_hook(self.winId())
5. 連接 resizeEvent → _update_button_rects()
```

### 5.3 `_update_button_rects()` 方法

```python
def _update_button_rects(self):
    """在視窗大小改變時，將四個按鈕的螢幕座標通知 C++ DLL"""
    for btn in [self.btn_pin, self.btn_max, self.btn_min, self.btn_close]:
        rect = btn.geometry()  # 相對於 parent widget
        # 轉換為相對於 MainWindow 客戶端座標後傳給 DLL
    win_titlebar.update_rects(pin_rect, max_rect, min_rect, close_rect)
```

### 5.4 釘選邏輯

```python
def _on_pin_toggled(self, checked: bool):
    flags = self.windowFlags()
    if checked:
        flags |= Qt.WindowType.WindowStaysOnTopHint
        # 套用發光邊框特效
    else:
        flags &= ~Qt.WindowType.WindowStaysOnTopHint
        # 移除特效
    self.setWindowFlags(flags)
    self.show()  # setWindowFlags 需要重新 show()
    
    # 持久化到 config
    self.config.set("ui_state", "always_on_top", checked)
    self.config.save_config()
```

---

## 6. 狀態持久化

### 6.1 `config.json` 新增欄位

```json
{
  "ui_state": {
    "always_on_top": false,
    "custom_titlebar": true
  }
}
```

| 欄位 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `always_on_top` | `bool` | `false` | 釘選狀態，重啟後恢復 |
| `custom_titlebar` | `bool` | `true` | 是否啟用自定義標題列（預留停用出口） |

### 6.2 啟動還原流程

```
MainWindow.__init__()
  → always_on_top = config.get("ui_state", {}).get("always_on_top", False)
  → 若 True：設定 WindowStaysOnTopHint + 更新 btn_pin.setChecked(True)
```

---

## 7. 特殊情境處理

### 7.1 `PreviewOverlay`（大圖預覽）

- `PreviewOverlay` 是覆蓋在 `MainWindow` 之上的全螢幕 Widget。
- 若 `MainWindow` 已置頂，`PreviewOverlay` 會自動繼承置頂狀態（因為是子視窗）。
- **潛在衝突**：全螢幕預覽時，使用者無法拖拽圖片至被蓋住的下層視窗。
- **解決方向**：偵測到 Drag 開始（`dragEnterEvent`）時，暫時將 `MainWindow` 透明度降至 30%，讓使用者可以看到下方軟體的放置目標。

### 7.2 `setWindowFlags()` 的副作用

呼叫 `setWindowFlags()` 後必須再次呼叫 `self.show()`，會導致視窗短暫閃爍。  
**緩解方案**：在切換前後各呼叫一次 `self.setUpdatesEnabled(False/True)`，抑制重繪。

### 7.3 開發模式降級

若 `EyeSeeMoreWin.dll` 不存在（純 Python 開發環境），  
`core/win_titlebar.py` 的所有函式應靜默跳過，不拋出例外，  
讓程式以「有系統標題列 + 無 Snap Layouts」模式正常執行。

---

## 8. 實作分工與順序建議

```
Phase 1：Pure Python 原型
  ├── 在 TopBar 加入 btn_pin (checkable QPushButton)
  ├── 實作 Always on Top 邏輯（setWindowFlags）
  ├── 連接 Ctrl+T 快捷鍵
  └── 持久化至 config.json → ui_state.always_on_top

Phase 2：自定義標題列（Pure Python）
  ├── 設定 FramelessWindowHint
  ├── 加入 btn_min / btn_max / btn_close 至 TopBar
  ├── 覆寫 mousePressEvent / mouseMoveEvent 實現拖動
  └── 覆寫 resizeEvent 更新 btn_max 的圖示（□ / ❐）

Phase 3：C++ DLL（Win32 原生整合）
  ├── 建立 src_cpp/win_titlebar/ 子專案
  ├── 在現有 CMakeLists.txt 加入 DLL build target
  ├── 實作 WM_NCHITTEST / WM_NCCALCSIZE 攔截
  ├── 撰寫 core/win_titlebar.py ctypes 橋接
  └── 整合測試：Snap Layouts、縮放手感、置頂切換

Phase 4：QSS 主題整合
  └── 在 themes/base_style.qss 補充 PinBtn / WinMinBtn / WinMaxBtn / WinCloseBtn 樣式
      （hover 效果、關閉按鈕變紅、釘選中的主題色發光）
```

---

## 9. 檔案影響清單

| 檔案 | 操作 | 說明 |
|------|------|------|
| `ui/main_window_ui.py` | **修改** | TopBar 加入四個控制按鈕 |
| `Blur-main.py` (MainWindow) | **修改** | 加入拖動、釘選、快捷鍵邏輯 |
| `core/config_manager.py` | **修改** | `ui_state` 新增 `always_on_top` 預設值 |
| `core/win_titlebar.py` | **新增** | ctypes DLL 橋接模組 |
| `themes/base_style.qss` | **修改** | 新增自定義視窗控制按鈕 QSS |
| `src_cpp/win_titlebar/titlebar_hook.h` | **新增** | C++ DLL 公開介面定義 |
| `src_cpp/win_titlebar/titlebar_hook.cpp` | **新增** | Win32 WndProc 攔截實作 |
| `src_cpp/CMakeLists.txt` | **修改** | 加入 DLL build target |

---

## 10. 開放問題（待決策）

| # | 問題 | 選項 |
|---|------|------|
| Q1 | `always_on_top` 預設值應為 `false` 還是讓使用者在設定頁選擇「記住上次狀態」？ | 建議預設 `false`，進階選項在 SettingsDialog 提供 |
| Q2 | Phase 2 實作邊框縮放，是否使用第三方庫 `PyQt-Frameless-Window` 加速開發？ | 若追求主題完整性建議手寫；若求快可用第三方庫 |
| Q3 | C++ DLL 是否納入現有 CMake build pipeline 自動產出，還是手動編譯後放入 repo？ | 建議納入 CMake，與 `EyeSeeMore_Launcher` 同步構建 |
