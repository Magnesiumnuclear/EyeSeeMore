#pragma once
// ============================================================
//  EyeSeeMore — titlebar_hook.h
//  C ABI 公開介面，供 Python ctypes 呼叫
//
//  設計書 §4.2：
//    ESM_InstallHook   — 安裝 WndProc 掛鉤、補回 DWM 陰影
//    ESM_SetButtonRects— 更新四個按鈕的感應座標
//    ESM_UninstallHook — 還原原始 WndProc（程式關閉時呼叫）
//    ESM_SetMenuState  — 更新系統選單勾選狀態（供 Python 呼叫）
// ============================================================

#include <windows.h>

// ──────────────────────────────────────────────────────────────
//  自定義系統選單項目 ID
//  必須避開 Windows 保留的 SC_* 範圍（0xF000 以上）
// ──────────────────────────────────────────────────────────────
#define IDM_PAUSE_SCAN   0xA000   // 暫停 / 繼續 掃描圖片
#define IDM_CANCEL_SCAN  0xA001   // 取消掃描

// ──────────────────────────────────────────────────────────────
//  WM_APP 通知碼（DLL → Python）
//   WM_APP+1 (0x8001): 已用於最大化按鈕 hover
//   WM_APP+2 (0x8002): 使用者點擊「暫停/繼續掃描」
//   WM_APP+3 (0x8003): 使用者點擊「取消掃描」
// ──────────────────────────────────────────────────────────────
#define WM_ESM_PAUSE_SCAN   (WM_APP + 2)
#define WM_ESM_CANCEL_SCAN  (WM_APP + 3)

#ifdef TITLEBARHOOK_EXPORTS
#   define ESM_API __declspec(dllexport)
#else
#   define ESM_API __declspec(dllimport)
#endif

#ifdef __cplusplus
extern "C" {
#endif

// ── 安裝 WndProc 掛鉤 ─────────────────────────────────────
// hwnd            : PyQt6 視窗的 HWND（由 int(self.winId()) 取得）
// titlebar_height : TopBar 邏輯像素高度（未 DPI 縮放）
// dpr             : devicePixelRatio（高 DPI 螢幕 >1.0）
// 回傳：0 = 成功，非 0 = 錯誤碼
ESM_API int ESM_InstallHook(HWND hwnd, int titlebar_height, float dpr);

// ── 更新四個按鈕感應區域 ─────────────────────────────────
// 座標為相對於 MainWindow 客戶端左上角（邏輯像素，未 DPI 縮放）
// 每個按鈕以 left, top, width, height 四個 int 傳入
ESM_API void ESM_SetButtonRects(
    int close_l, int close_t, int close_w, int close_h,
    int max_l,   int max_t,   int max_w,   int max_h,
    int min_l,   int min_t,   int min_w,   int min_h,
    int pin_l,   int pin_t,   int pin_w,   int pin_h
);

// ── 移除 WndProc 掛鉤 ─────────────────────────────────────
ESM_API void ESM_UninstallHook(HWND hwnd);

// ── 更新系統選單項目的勾選狀態 ─────────────────────────────
// item_id : IDM_PAUSE_SCAN 或 IDM_CANCEL_SCAN
// checked : TRUE = 顯示勾選符號，FALSE = 移除勾選符號
ESM_API void ESM_SetMenuState(int item_id, BOOL checked);

#ifdef __cplusplus
} // extern "C"
#endif
