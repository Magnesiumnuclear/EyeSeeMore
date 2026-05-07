#pragma once
// ============================================================
//  EyeSeeMore — titlebar_hook.h
//  C ABI 公開介面，供 Python ctypes 呼叫
//
//  設計書 §4.2：
//    ESM_InstallHook   — 安裝 WndProc 掛鉤、補回 DWM 陰影
//    ESM_SetButtonRects— 更新四個按鈕的感應座標
//    ESM_UninstallHook — 還原原始 WndProc（程式關閉時呼叫）
// ============================================================

#include <windows.h>

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

#ifdef __cplusplus
} // extern "C"
#endif
