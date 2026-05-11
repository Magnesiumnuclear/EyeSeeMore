// ============================================================
//  EyeSeeMore — titlebar_hook.cpp
//  Win32 自定義標題列核心實作
//
//  功能：
//   1. 子類化 WndProc — 攔截 WM_NCCALCSIZE / WM_NCHITTEST
//   2. WM_NCCALCSIZE  — 移除 Non-Client Area，交由 Qt 全權繪製
//   3. WM_NCHITTEST   — 回傳正確 Hit-Test code：
//        - 8 方向邊框縮放（Windows 接管動畫）
//        - HTMAXBUTTON → 觸發 Windows 11 Snap Layouts
//        - HTCAPTION   → TopBar 空白區允許拖動
//   4. DwmExtendFrameIntoClientArea(-1) — 補回 DWM 陰影與 Win11 圓角
//
//  設計書參考：DESIGN_CustomTitleBar.md §4
// ============================================================

#define WIN32_LEAN_AND_MEAN
// TITLEBARHOOK_EXPORTS 由編譯器命令列 -DTITLEBARHOOK_EXPORTS 注入，
// 此處不重複 #define，避免 -D 與原始碼雙重定義的 warning
#include "titlebar_hook.h"
#include <dwmapi.h>
#include <windowsx.h>  // GET_X_LPARAM / GET_Y_LPARAM

// DWM 函式庫（MinGW 以 -ldwmapi 連結，MSVC 以 #pragma comment 連結）
#ifdef _MSC_VER
#   pragma comment(lib, "dwmapi.lib")
#   pragma comment(lib, "user32.lib")
#endif

// ─────────────────────────────────────────────────────────────
//  模組層級靜態狀態
//  只支援單一視窗（EyeSeeMore 只有一個 MainWindow）
// ─────────────────────────────────────────────────────────────
static HWND   s_hwnd          = NULL;
static WNDPROC s_old_wndproc  = NULL;

// 按鈕感應矩形（left, top, right, bottom；邏輯像素*dpr後的實際像素）
static RECT s_close_rect = {};
static RECT s_max_rect   = {};
static RECT s_min_rect   = {};
static RECT s_pin_rect   = {};

static int   s_titlebar_height = 60;   // 邏輯像素
static float s_dpr             = 1.0f; // devicePixelRatio
static bool  s_max_hover       = false; // NC hover 追蹤（WM_APP+1 通知 Python）

// ─────────────────────────────────────────────────────────────
//  工具函式
// ─────────────────────────────────────────────────────────────
static inline BOOL PtInR(const RECT& r, LONG x, LONG y)
{
    return (x >= r.left) && (x < r.right) && (y >= r.top) && (y < r.bottom);
}

// ─────────────────────────────────────────────────────────────
//  自訂 WndProc
// ─────────────────────────────────────────────────────────────
static LRESULT CALLBACK HookWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    // ── 1. 移除 Non-Client Area ────────────────────────────
    // 設計書 §4.4：回傳 0 告訴 Windows 不繪製系統標題列框架，
    // DWM 仍負責視窗陰影與 Win11 圓角
    if (msg == WM_NCCALCSIZE && wParam == TRUE)
        return 0;

    // ── 1b. NC 左鍵按下 ────────────────────────────────────
    if (msg == WM_NCLBUTTONDOWN) {
        // 邊框縮放：
        // DefWindowProcW(WM_NCLBUTTONDOWN, HTcorner) 對 NC 位置做驗證，
        // 因 WM_NCCALCSIZE 回傳 0 導致角落驗證失敗。
        // 改用 ReleaseCapture + PostMessage(WM_SYSCOMMAND, SC_SIZE+dir)。
        if (wParam >= HTLEFT && wParam <= HTBOTTOMRIGHT) {
            ReleaseCapture();
            PostMessageW(hwnd, WM_SYSCOMMAND,
                SC_SIZE | (WPARAM)(wParam - HTLEFT + 1), lParam);
            return 0;
        }
        // 最大化按鈕直接點擊（未選擇 Snap Layout）：
        // 使用 WM_SYSCOMMAND SC_MAXIMIZE/SC_RESTORE 讓 OS 直接處理最大化，
        // Qt 的 resizeEvent 會自動偵測狀態變化並同步按鈕圖示。
        if (wParam == HTMAXBUTTON) {
            ReleaseCapture();
            BOOL is_max = IsZoomed(hwnd);
            PostMessageW(hwnd, WM_SYSCOMMAND, is_max ? SC_RESTORE : SC_MAXIMIZE, lParam);
            return 0;
        }
    }

    // ── 1c. NC Mouse Move/Leave → 通知 Python WinMaxBtn hover 狀態 ──────────
    // WM_NCMOUSEMOVE.wParam == HTMAXBUTTON 表示滑鼠在最大化按鈕 NC 區域移動，
    // 發 WM_APP+1(wParam=1) 讓 Python 開啟 hover 視覺；
    // 滑鼠移往其他 NC 區或完全離開 NC 區時，發 WM_APP+1(wParam=0) 關閉。
    if (msg == WM_NCMOUSEMOVE) {
        bool over_max = (wParam == HTMAXBUTTON);
        if (over_max && !s_max_hover) {
            s_max_hover = true;
            PostMessageW(hwnd, WM_APP + 1, 1, 0);
            // 申請 WM_NCMOUSELEAVE 通知（鼠標完全離開 NC 區域時觸發）
            TRACKMOUSEEVENT tme = { sizeof(tme), TME_NONCLIENT | TME_LEAVE, hwnd, 0 };
            TrackMouseEvent(&tme);
        } else if (!over_max && s_max_hover) {
            s_max_hover = false;
            PostMessageW(hwnd, WM_APP + 1, 0, 0);
        }
    }
    if (msg == WM_NCMOUSELEAVE) {
        if (s_max_hover) {
            s_max_hover = false;
            PostMessageW(hwnd, WM_APP + 1, 0, 0);
        }
    }

    // ── 1c. 縮放游標 ───────────────────────────────────────
    // Qt (FramelessWindowHint) 攔截 WM_SETCURSOR 並重設為預設箭頭，
    // 導致邊框 hover 時游標不顯示 ⬌⬍。此處先行回傳正確游標。
    // MinGW 環境 IDC_* 為 LPSTR，LoadCursorW 需 LPCWSTR；
    // 使用 MAKEINTRESOURCEW(numeric_id) 繞過型別不符問題。
    if (msg == WM_SETCURSOR) {
        WORD cur_id = 0;
        switch (LOWORD(lParam)) {
            case HTLEFT:      case HTRIGHT:       cur_id = 32644; break; // IDC_SIZEWE
            case HTTOP:       case HTBOTTOM:      cur_id = 32645; break; // IDC_SIZENS
            case HTTOPLEFT:   case HTBOTTOMRIGHT: cur_id = 32642; break; // IDC_SIZENWSE
            case HTTOPRIGHT:  case HTBOTTOMLEFT:  cur_id = 32643; break; // IDC_SIZENESW
            default: break;
        }
        if (cur_id) {
            SetCursor(LoadCursorW(NULL, MAKEINTRESOURCEW(cur_id)));
            return TRUE;
        }
    }

    // ── 2. Hit-Test 判斷 ───────────────────────────────────
    if (msg == WM_NCHITTEST)
    {
        // 螢幕座標 → 客戶端座標
        POINT pt = { GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam) };
        ScreenToClient(hwnd, &pt);

        RECT rc;
        GetClientRect(hwnd, &rc);
        LONG w = rc.right;
        LONG h = rc.bottom;

        // 邊框縮放感應寬度（已依 DPI 縮放）
        LONG bw = static_cast<LONG>(6.0f * s_dpr);
        if (bw < 1) bw = 1;

        BOOL on_left   = (pt.x < bw);
        BOOL on_right  = (pt.x >= w - bw);
        BOOL on_top    = (pt.y < bw);
        BOOL on_bottom = (pt.y >= h - bw);

        // 四個角（斜向縮放，優先判斷）
        if (on_top    && on_left)  return HTTOPLEFT;
        if (on_top    && on_right) return HTTOPRIGHT;
        if (on_bottom && on_left)  return HTBOTTOMLEFT;
        if (on_bottom && on_right) return HTBOTTOMRIGHT;

        // 四條邊
        if (on_left)   return HTLEFT;
        if (on_right)  return HTRIGHT;
        if (on_top)    return HTTOP;
        if (on_bottom) return HTBOTTOM;

        // ── 按鈕感應區（座標已是縮放後實際像素）──
        // 設計書 §4.3
        if (PtInR(s_close_rect, pt.x, pt.y)) return HTCLIENT;   // Qt 處理關閉
        // HTMAXBUTTON：讓 Windows 11 彈出 Snap Layouts 選單（hover 觸發）
        // 點擊後由 WM_NCLBUTTONDOWN 攔截，透過 WM_APP+1 通知 Python
        if (PtInR(s_max_rect,   pt.x, pt.y)) return HTMAXBUTTON;
        if (PtInR(s_min_rect,   pt.x, pt.y)) return HTCLIENT;   // Qt 處理最小化
        if (PtInR(s_pin_rect,   pt.x, pt.y)) return HTCLIENT;   // Qt 處理釘選

        // ── TopBar / 客戶端區域 ────────────────────────────
        // 所有非邊框區域一律回傳 HTCLIENT，讓 Qt 完全控制事件分發。
        // 視窗拖曳改由 Python event filter 在 TopBar 空白區觸發
        // ReleaseCapture() + PostMessageW(WM_NCLBUTTONDOWN, HTCAPTION)。
        return HTCLIENT;
    }

    // 其餘訊息交回原始 WndProc
    return CallWindowProcW(s_old_wndproc, hwnd, msg, wParam, lParam);
}

// ─────────────────────────────────────────────────────────────
//  公開 C ABI 實作
// ─────────────────────────────────────────────────────────────
extern "C" {

ESM_API int ESM_InstallHook(HWND hwnd, int titlebar_height, float dpr)
{
    if (!hwnd || !IsWindow(hwnd))
        return 1;  // 無效 HWND

    if (s_hwnd != NULL)
        return 0;  // 已安裝，冪等

    s_hwnd             = hwnd;
    s_titlebar_height  = titlebar_height;
    s_dpr              = (dpr > 0.0f) ? dpr : 1.0f;

    // 1. 子類化 WndProc
    //    SetWindowLongPtrW 回傳舊 WndProc 的 LONG_PTR（64-bit 上即 64-bit 指標）
    //    必須轉為 WNDPROC 而非 LONG 以避免 32-bit 截斷（ctypes 版的 bug 根源）
    s_old_wndproc = reinterpret_cast<WNDPROC>(
        SetWindowLongPtrW(hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(HookWndProc))
    );
    if (!s_old_wndproc) {
        s_hwnd = NULL;
        return 2;  // SetWindowLongPtrW 失敗
    }

    // 2. 補回 Windows 樣式（Qt FramelessWindowHint 全部移除了）
    //    WS_THICKFRAME   — DefWindowProcW 縮放迴圈依賴此樣式
    //    WS_CAPTION      — DWM 陰影/圓角正常運作
    //    WS_MAXIMIZEBOX  — Windows 11 Snap Layouts 需要此樣式才會顯示選單
    //    WS_MINIMIZEBOX  — 最小化按鈕 NC 追蹤（選用，保持一致性）
    //    視覺上不顯示系統框：WM_NCCALCSIZE 回傳 0 已消除所有 NC 繪製。
    LONG_PTR style = GetWindowLongPtrW(hwnd, GWL_STYLE);
    SetWindowLongPtrW(hwnd, GWL_STYLE,
        style | WS_THICKFRAME | WS_CAPTION | WS_MAXIMIZEBOX | WS_MINIMIZEBOX);

    // 3. DWM：將 frame 延伸至整個客戶區 → 補回視窗陰影與 Win11 圓角
    //    (-1, -1, -1, -1) = 延伸至整個視窗
    MARGINS margins = { -1, -1, -1, -1 };
    DwmExtendFrameIntoClientArea(hwnd, &margins);

    // 3. 通知 Windows 重新計算視窗框架（觸發 WM_NCCALCSIZE）
    SetWindowPos(hwnd, NULL, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);

    // ───────────────────────────────────────────────────────────────
    // 4. 插入自定義系統選單項目
    // 原生 WndProc 裝好後才取得 hSysMenu，確保選單句柄正確對應此視窗。
    // ───────────────────────────────────────────────────────────────
    HMENU hSysMenu = GetSystemMenu(hwnd, FALSE);
    if (hSysMenu) {
        AppendMenuW(hSysMenu, MF_SEPARATOR, 0, NULL);
        AppendMenuW(hSysMenu, MF_STRING, IDM_PAUSE_SCAN,  L"暫停 / 繼續 掃描圖片");
        AppendMenuW(hSysMenu, MF_STRING, IDM_CANCEL_SCAN, L"取消掃描");
    }

    return 0;
}

ESM_API void ESM_SetButtonRects(
    int close_l, int close_t, int close_w, int close_h,
    int max_l,   int max_t,   int max_w,   int max_h,
    int min_l,   int min_t,   int min_w,   int min_h,
    int pin_l,   int pin_t,   int pin_w,   int pin_h)
{
    // 儲存為 RECT（left, top, right, bottom）
    // 輸入為 left, top, width, height（與 Qt geometry() 一致）
    s_close_rect = { close_l, close_t, close_l + close_w, close_t + close_h };
    s_max_rect   = { max_l,   max_t,   max_l   + max_w,   max_t   + max_h   };
    s_min_rect   = { min_l,   min_t,   min_l   + min_w,   min_t   + min_h   };
    s_pin_rect   = { pin_l,   pin_t,   pin_l   + pin_w,   pin_t   + pin_h   };
}

ESM_API void ESM_UninstallHook(HWND hwnd)
{
    if (!s_old_wndproc || s_hwnd != hwnd)
        return;

    SetWindowLongPtrW(hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(s_old_wndproc));
    s_old_wndproc = NULL;
    s_hwnd        = NULL;
    s_max_hover   = false;
}

ESM_API void ESM_SetMenuState(int item_id, BOOL checked)
{
    // 更新系統選單項目的勾選符號狀態
    // Python 端在暫停/繼續切換後呼叫此函式同步選單視覺
    if (!s_hwnd) return;
    HMENU hSysMenu = GetSystemMenu(s_hwnd, FALSE);
    if (!hSysMenu) return;

    UINT uCheck = checked ? (MF_BYCOMMAND | MF_CHECKED) : (MF_BYCOMMAND | MF_UNCHECKED);
    CheckMenuItem(hSysMenu, static_cast<UINT>(item_id), uCheck);
}

} // extern "C"
