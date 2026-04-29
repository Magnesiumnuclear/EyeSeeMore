/**
 * EyeSeeMore – main_launcher.cpp
 * ─────────────────────────────────────────────────────────────────────────────
 * 架構職責：
 *   1. 從登錄檔讀取安裝路徑
 *   2. 讀取 user_config.json，取得使用者目前選定的「主題」與「語言」
 *   3. 載入對應 themes/<id>.json，解析 Splash Screen 的背景色與文字色
 *   4. 透過環境變數 ESM_THEME / ESM_LANG 將偏好設定傳遞給 Python 行程
 *   5. 以背景執行緒呼叫 python310.dll，執行 Blur-main.py
 *   6. 主執行緒顯示與 Python UI 主題同步的 Splash Screen，
 *      偵測到主視窗出現後自動淡出
 *
 * 目錄結構（安裝在 %LOCALAPPDATA%\EyeSeeMore\）：
 *   EyeSeeMore_Launcher.exe
 *   python310.dll
 *   Blur-main.py
 *   core/ ui/ utils/ languages/ models/
 *   themes/
 *       base_style.qss
 *       dark.json          ← 顏色變數定義
 *       light.json
 *   user_config.json       ← C++ 與 Python 共用的輕量偏好橋接檔
 *   config.json            ← Python 主程式的完整應用設定
 */

#include <windows.h>
#include <string>
#include <thread>

// ─── Python DLL 函數指標型別 ───────────────────────────────────────────────
typedef void (*Py_Initialize_t)(void);
typedef int  (*PyRun_SimpleString_t)(const char*);
typedef void (*Py_Finalize_t)(void);

// Python 主視窗標題，用於偵測 Splash 解除時機
const wchar_t* TARGET_TITLE = L"EyeSeeMore-(Alpha)";


// ═══════════════════════════════════════════════════════════════════════════
// § 0  輕量工具：Win32 檔案讀取 / 最小化 JSON 字串值取出 / 色彩解析
// ═══════════════════════════════════════════════════════════════════════════

/**
 * 以 Win32 API 將整個 UTF-8 文字檔讀入 std::string。
 * 選用 Win32 ReadFile 而非 std::ifstream，確保在各版本 MSVC CRT 下行為一致。
 */
static std::string ReadFileUtf8(const std::wstring& path) {
    HANDLE h = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ,
                           nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return {};

    DWORD size = GetFileSize(h, nullptr);
    if (!size || size == INVALID_FILE_SIZE) { CloseHandle(h); return {}; }

    std::string buf(size, '\0');
    DWORD read = 0;
    ReadFile(h, &buf[0], size, &read, nullptr);
    CloseHandle(h);
    buf.resize(read);
    return buf;
}

/**
 * 從一段 JSON 文字中取出指定 key 的字串值。
 * 僅支援 "key": "value" 的純字串格式，這對我們已知的 JSON 結構完全足夠，
 * 不引入外部 JSON 函式庫以保持零相依。
 *
 * 已知限制：若同名 key 出現多次，回傳第一個。
 * 對於 user_config.json（扁平 2-key 檔案）與 themes/*.json（無重複頂層字串 key）
 * 此行為完全正確。
 */
static std::string JsonGetStr(const std::string& json, const std::string& key) {
    const std::string needle = "\"" + key + "\"";
    size_t kpos = json.find(needle);
    if (kpos == std::string::npos) return {};

    size_t colon = json.find(':', kpos + needle.size());
    if (colon == std::string::npos) return {};

    size_t q1 = json.find('"', colon + 1);
    if (q1 == std::string::npos) return {};

    size_t q2 = json.find('"', q1 + 1);
    if (q2 == std::string::npos) return {};

    return json.substr(q1 + 1, q2 - q1 - 1);
}

/**
 * 將 HTML 色彩字串轉換為 Win32 COLORREF（0x00BBGGRR）。
 * 支援：
 *   "#RRGGBB"     ─ 標準 6 字元，直接對應
 *   "#AARRGGBB"   ─ 8 字元（Qt 部分格式），自動忽略最前面的 Alpha 位元組
 * 解析失敗時回傳 fallback。
 */
static COLORREF HexColor(const std::string& hex, COLORREF fallback) {
    std::string h = hex;
    if (!h.empty() && h[0] == '#') h.erase(0, 1);
    if (h.size() == 8) h.erase(0, 2);   // strip Alpha, e.g. "f0232323" → "232323"
    if (h.size() != 6) return fallback;

    try {
        int r = std::stoi(h.substr(0, 2), nullptr, 16);
        int g = std::stoi(h.substr(2, 2), nullptr, 16);
        int b = std::stoi(h.substr(4, 2), nullptr, 16);
        return RGB(r, g, b);
    } catch (...) {
        return fallback;
    }
}


// ═══════════════════════════════════════════════════════════════════════════
// § 1  啟動畫面主題：SplashTheme 結構 + 從 user_config / themes 載入
// ═══════════════════════════════════════════════════════════════════════════

/**
 * 保存 Splash Screen 所需的三個顏色，預設值對應 dark.json：
 *   bg    ← colors.bg_app   → 視窗背景
 *   title ← colors.primary  → 主程式名稱文字
 *   sub   ← colors.text_sec → 副標題「載入中...」
 */
struct SplashTheme {
    COLORREF bg    = RGB(30,  30,  30);   // #1e1e1e  (dark.bg_app)
    COLORREF title = RGB(96, 205, 255);   // #60cdff  (dark.primary)
    COLORREF sub   = RGB(204, 204, 204);  // #cccccc  (dark.text_sec)
};

/**
 * 讀取流：
 *   installDir\user_config.json  →  取得 "theme" 欄位（如 "dark"）
 *   installDir\themes\dark.json  →  取得 colors.bg_app / primary / text_sec
 * 任一步驟失敗均回傳 SplashTheme 預設值（深色），確保啟動不閃退。
 */
static SplashTheme LoadSplashTheme(const std::wstring& installDir) {
    SplashTheme t;

    std::string ucfg = ReadFileUtf8(installDir + L"\\user_config.json");
    if (ucfg.empty()) return t;

    std::string themeId = JsonGetStr(ucfg, "theme");
    if (themeId.empty()) themeId = "dark";

    // ASCII 主題 ID 轉寬字元路徑（主題名稱只含 ASCII，安全）
    std::wstring themePath = installDir + L"\\themes\\"
        + std::wstring(themeId.begin(), themeId.end()) + L".json";

    std::string tj = ReadFileUtf8(themePath);
    if (tj.empty()) return t;

    auto bgStr  = JsonGetStr(tj, "bg_app");
    auto priStr = JsonGetStr(tj, "primary");
    auto subStr = JsonGetStr(tj, "text_sec");

    if (!bgStr.empty())  t.bg    = HexColor(bgStr,  t.bg);
    if (!priStr.empty()) t.title = HexColor(priStr, t.title);
    if (!subStr.empty()) t.sub   = HexColor(subStr, t.sub);

    return t;
}


// ═══════════════════════════════════════════════════════════════════════════
// § 2  Splash Screen 視窗回呼
// ═══════════════════════════════════════════════════════════════════════════

LRESULT CALLBACK SplashWndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {

    // WM_CREATE：將呼叫端傳入的 SplashTheme* 存入 GWLP_USERDATA，
    //            讓後續的 WM_PAINT 能無狀態地取到色彩。
    case WM_CREATE: {
        auto* cs = reinterpret_cast<LPCREATESTRUCT>(lParam);
        SetWindowLongPtrW(hWnd, GWLP_USERDATA,
                          reinterpret_cast<LONG_PTR>(cs->lpCreateParams));
        break;
    }

    case WM_PAINT: {
        auto* theme = reinterpret_cast<const SplashTheme*>(
            GetWindowLongPtrW(hWnd, GWLP_USERDATA));

        COLORREF bgCol    = theme ? theme->bg    : RGB(30,  30,  30);
        COLORREF titleCol = theme ? theme->title : RGB(96, 205, 255);
        COLORREF subCol   = theme ? theme->sub   : RGB(204, 204, 204);

        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hWnd, &ps);

        RECT rc;
        GetClientRect(hWnd, &rc);

        // 背景填色
        HBRUSH hBg = CreateSolidBrush(bgCol);
        FillRect(hdc, &rc, hBg);
        DeleteObject(hBg);
        SetBkMode(hdc, TRANSPARENT);

        // 主標題：EyeSeeMore（大 / Bold）
        SetTextColor(hdc, titleCol);
        HFONT hBig = CreateFontW(
            36, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
            OUT_OUTLINE_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
            VARIABLE_PITCH, L"Segoe UI");
        HFONT hOld = static_cast<HFONT>(SelectObject(hdc, hBig));

        RECT rcTitle = rc;
        rcTitle.bottom = rc.bottom / 2 + 6;
        DrawTextW(hdc, L"EyeSeeMore", -1, &rcTitle, DT_CENTER | DT_BOTTOM | DT_SINGLELINE);

        SelectObject(hdc, hOld);
        DeleteObject(hBig);

        // 副標題：AI Vision Engine（小 / Regular）
        SetTextColor(hdc, subCol);
        HFONT hSm = CreateFontW(
            15, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
            OUT_OUTLINE_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
            VARIABLE_PITCH, L"Segoe UI");
        SelectObject(hdc, hSm);

        RECT rcSub = rc;
        rcSub.top = rc.bottom / 2 + 12;
        DrawTextW(hdc, L"AI Vision Engine  |  \u8f09\u5165\u4e2d\u2026", -1, &rcSub,
                  DT_CENTER | DT_TOP | DT_SINGLELINE);

        SelectObject(hdc, hOld);
        DeleteObject(hSm);
        EndPaint(hWnd, &ps);
        break;
    }

    // 每 100 ms 輪詢：Python 主視窗就緒後銷毀 Splash
    // 同時偵測主視窗標題與首次執行歡迎視窗標題，避免首次安裝時 Splash 永遠不消失
    case WM_TIMER: {
        const wchar_t* TITLES[] = {
            L"EyeSeeMore-(Alpha)",
            L"EyeSeeMore - Welcome",
            nullptr
        };
        for (int i = 0; TITLES[i]; ++i) {
            HWND hMain = FindWindowW(nullptr, TITLES[i]);
            if (hMain && IsWindowVisible(hMain)) {
                KillTimer(hWnd, 1);
                DestroyWindow(hWnd);
                break;
            }
        }
        break;
    }

    case WM_DESTROY:
        PostQuitMessage(0);
        break;

    default:
        return DefWindowProc(hWnd, msg, wParam, lParam);
    }
    return 0;
}


// ═══════════════════════════════════════════════════════════════════════════
// § 3  Python 執行緒
// ═══════════════════════════════════════════════════════════════════════════

static void PythonThread(std::wstring wsRoot) {
    HMODULE hPy = LoadLibraryW((wsRoot + L"\\python310.dll").c_str());
    if (!hPy) return;

    auto Py_Init  = reinterpret_cast<Py_Initialize_t>(GetProcAddress(hPy, "Py_Initialize"));
    auto PyRunStr = reinterpret_cast<PyRun_SimpleString_t>(GetProcAddress(hPy, "PyRun_SimpleString"));
    auto Py_Fin   = reinterpret_cast<Py_Finalize_t>(GetProcAddress(hPy, "Py_Finalize"));

    if (!Py_Init || !PyRunStr || !Py_Fin) { FreeLibrary(hPy); return; }

    Py_Init();

    int sz = WideCharToMultiByte(CP_UTF8, 0, wsRoot.c_str(), -1, nullptr, 0, nullptr, nullptr);
    std::string utf8Root(sz, '\0');
    WideCharToMultiByte(CP_UTF8, 0, wsRoot.c_str(), -1, &utf8Root[0], sz, nullptr, nullptr);
    utf8Root.pop_back(); 

    // 🌟 強化版引導腳本：加入 Qt 插件路徑修正與崩潰日誌輸出
    std::string script =
        "import sys, os, traceback\n"
        "dir = r'" + utf8Root + "'\n"
        "sys.path.insert(0, dir)\n"
        "_sp = os.path.join(dir, 'Lib', 'site-packages')\n"
        "if _sp not in sys.path:\n"
        "    sys.path.insert(1, _sp)\n"
        "import site\n"
        
        // --- 核心修復：告訴 PyQt6 插件的絕對路徑 ---
        "qt_plugins = os.path.join(_sp, 'PyQt6', 'Qt6', 'plugins')\n"
        "os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = qt_plugins\n"
        "os.chdir(dir)\n"
        
        // --- 前面的設定環境變數都不變 ---
        "sys.argv = ['Blur-main.py']\n"
        "__file__ = os.path.join(dir, 'Blur-main.py')\n"
        
        // --- 修改 try 區塊，使用真實的 __main__ 模組 ---
        "try:\n"
        "    import __main__\n"                                    // 1. 取得系統真正的 __main__
        "    __main__.__file__ = __file__\n"                       // 2. 綁定檔案路徑
        "    with open('Blur-main.py', 'r', encoding='utf-8') as f:\n"
        "        code = compile(f.read(), __file__, 'exec')\n"
        "        exec(code, __main__.__dict__)\n"                  // 3. 🌟 關鍵：直接在系統 __main__ 的字典中執行！
        "except Exception as e:\n"
        "    with open('launcher_error.log', 'w', encoding='utf-8') as log:\n"
        "        traceback.print_exc(file=log)\n";

    PyRunStr(script.c_str());
    Py_Fin();
    FreeLibrary(hPy);
}


// ═══════════════════════════════════════════════════════════════════════════
// § 4  WinMain 入口
// ═══════════════════════════════════════════════════════════════════════════

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int) {

    // ── A. 讀取安裝路徑（由 installer 寫入登錄檔） ──────────────────────
    HKEY hKey;
    wchar_t installPath[MAX_PATH] = {};
    DWORD bufSize = sizeof(installPath);
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\EyeSeeMore",
                      0, KEY_READ, &hKey) != ERROR_SUCCESS) return 1;
    RegQueryValueExW(hKey, L"InstallPath", nullptr, nullptr,
                     reinterpret_cast<LPBYTE>(installPath), &bufSize);
    RegCloseKey(hKey);
    std::wstring wsRoot(installPath);

    // ── B. 讀取使用者偏好 → 設定環境變數傳遞給 Python ──────────────────
    //
    //   橋接策略（環境變數 vs. 檔案）：
    //     ┌─────────────────┬──────────────────────────────────────┐
    //     │ 傳遞方向         │ 機制                                  │
    //     ├─────────────────┼──────────────────────────────────────┤
    //     │ C++ → Python    │ SetEnvironmentVariableA("ESM_THEME") │
    //     │ Python → C++    │ 寫入 user_config.json（下次啟動讀取）  │
    //     └─────────────────┴──────────────────────────────────────┘
    //
    //   Python 端讀法：
    //     theme = os.environ.get("ESM_THEME", "dark")
    //     lang  = os.environ.get("ESM_LANG",  "zh_TW")
    // ────────────────────────────────────────────────────────────────────
    std::string ucfg  = ReadFileUtf8(wsRoot + L"\\user_config.json");
    std::string theme = JsonGetStr(ucfg, "theme");
    std::string lang  = JsonGetStr(ucfg, "language");
    if (theme.empty()) theme = "dark";
    if (lang.empty())  lang  = "zh_TW";

    SetEnvironmentVariableA("ESM_THEME", theme.c_str());
    SetEnvironmentVariableA("ESM_LANG",  lang.c_str());

    // ── C. 解析 Splash Screen 色彩（必須在建立視窗前完成） ──────────────
    SplashTheme splashTheme = LoadSplashTheme(wsRoot);

    // ── D. 啟動 Python 背景執行緒 ────────────────────────────────────────
    std::thread pyThread(PythonThread, wsRoot);

    // ── E. 建立 Splash 視窗，透過 lpParam 傳入 SplashTheme 指標 ─────────
    //       splashTheme 存活於整個 WinMain 堆疊幀，指標安全有效。
    const wchar_t CLASS_NAME[] = L"EyeSeeMoreSplash";
    WNDCLASSW wc = {};
    wc.lpfnWndProc   = SplashWndProc;
    wc.hInstance     = hInstance;
    wc.lpszClassName = CLASS_NAME;
    wc.hCursor       = LoadCursor(nullptr, IDC_ARROW);
    RegisterClassW(&wc);

    const int w = 450, h = 250;
    const int x = (GetSystemMetrics(SM_CXSCREEN) - w) / 2;
    const int y = (GetSystemMetrics(SM_CYSCREEN) - h) / 2;

    HWND hWnd = CreateWindowExW(
        WS_EX_TOPMOST, CLASS_NAME, L"Splash", WS_POPUP,
        x, y, w, h, nullptr, nullptr, hInstance,
        &splashTheme   // ← WM_CREATE 透過 LPCREATESTRUCT.lpCreateParams 接收
    );
    ShowWindow(hWnd, SW_SHOW);
    SetTimer(hWnd, 1, 100, nullptr); // 每 100 ms 輪詢主視窗是否就緒

    // ── F. Splash 訊息迴圈（直到 DestroyWindow 觸發 WM_DESTROY） ─────────
    MSG msg = {};
    while (GetMessage(&msg, nullptr, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    // ── G. 等待 Python 主程式結束（使用者關閉 EyeSeeMore 後此行才解除） ──
    if (pyThread.joinable()) pyThread.join();

    return 0;
}