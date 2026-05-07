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

    // ── 1b. NC 左鍵按下 - 邊框縮放 ────────────────────────
    // Qt 搭配 FramelessWindowHint 時，其 WndProc 不會把縮放
    // HT code 轉給 DefWindowProcW，導致縮放迴圈無法啟動。
    // 直接呼叫 DefWindowProcW，繞過 Qt 的攔截。
    if (msg == WM_NCLBUTTONDOWN) {
        switch (wParam) {
            case HTLEFT:      case HTRIGHT:
            case HTTOP:       case HTBOTTOM:
            case HTTOPLEFT:   case HTTOPRIGHT:
            case HTBOTTOMLEFT: case HTBOTTOMRIGHT:
                return DefWindowProcW(hwnd, msg, wParam, lParam);
            default: break;
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
        // 全部回傳 HTCLIENT，讓 Qt 處理按鈕點擊事件與視覺回饋。
        // HTCLOSE/HTMAXBUTTON/HTMINBUTTON 會觸發 Windows NC 按鈕追蹤，
        // 導致 Qt 的 QPushButton 無法收到 clicked 訊號。
        if (PtInR(s_close_rect, pt.x, pt.y)) return HTCLIENT;
        if (PtInR(s_max_rect,   pt.x, pt.y)) return HTCLIENT;
        if (PtInR(s_min_rect,   pt.x, pt.y)) return HTCLIENT;
        if (PtInR(s_pin_rect,   pt.x, pt.y)) return HTCLIENT;

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

    // 2. DWM：將 frame 延伸至整個客戶區 → 補回視窗陰影與 Win11 圓角
    //    (-1, -1, -1, -1) = 延伸至整個視窗
    MARGINS margins = { -1, -1, -1, -1 };
    DwmExtendFrameIntoClientArea(hwnd, &margins);

    // 3. 通知 Windows 重新計算視窗框架（觸發 WM_NCCALCSIZE）
    SetWindowPos(hwnd, NULL, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);

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
}

} // extern "C"
