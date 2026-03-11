#include <windows.h>
#include <string>
#include <thread>
#include <atomic>

// --- 定義 Python 函數的指標型態 ---
typedef void (*Py_Initialize_t)(void);
typedef int (*PyRun_SimpleString_t)(const char*);
typedef void (*Py_Finalize_t)(void);

const wchar_t* TARGET_TITLE = L"EyeSeeMore-(Alpha)";

// ==========================================
// 1. 啟動畫面視窗回呼函數 (處理繪圖)
// ==========================================
LRESULT CALLBACK SplashWndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam) {
    switch (message) {
        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC hdc = BeginPaint(hWnd, &ps);
            
            RECT rect;
            GetClientRect(hWnd, &rect);
            HBRUSH hBrush = CreateSolidBrush(RGB(24, 24, 24));
            FillRect(hdc, &rect, hBrush);
            DeleteObject(hBrush);

            SetTextColor(hdc, RGB(77, 166, 255));
            SetBkMode(hdc, TRANSPARENT);
            HFONT hFont = CreateFontW(32, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, 
                                     OUT_OUTLINE_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, 
                                     VARIABLE_PITCH, L"Segoe UI");
            SelectObject(hdc, hFont);
            DrawTextW(hdc, L"EyeSeeMore\nAI Vision Engine", -1, &rect, DT_CENTER | DT_VCENTER | DT_WORDBREAK);
            
            DeleteObject(hFont);
            EndPaint(hWnd, &ps);
        } break;
        case WM_TIMER: {
            HWND hMainWnd = FindWindowW(NULL, TARGET_TITLE);
            // 確保視窗存在且已經顯示在畫面上
            if (hMainWnd && IsWindowVisible(hMainWnd)) {
                KillTimer(hWnd, 1);  // 1. 先停止計時器
                
                // ==========================================
                // [關鍵修復] 呼叫系統直接把這個啟動視窗從畫面上移除！
                // 這會自動觸發下面的 WM_DESTROY 事件。
                // ==========================================
                DestroyWindow(hWnd); 
            }
        } break;
        case WM_DESTROY:
            PostQuitMessage(0);
            break;
        default:
            return DefWindowProc(hWnd, message, wParam, lParam);
    }
    return 0;
}

// ==========================================
// 2. Python 執行緒函數
// ==========================================
void PythonThread(std::wstring wsInstallPath) {
    std::wstring dllPath = wsInstallPath + L"\\python310.dll";
    HMODULE hPython = LoadLibraryW(dllPath.c_str());
    if (!hPython) return;

    Py_Initialize_t Py_Initialize = (Py_Initialize_t)GetProcAddress(hPython, "Py_Initialize");
    PyRun_SimpleString_t PyRun_SimpleString = (PyRun_SimpleString_t)GetProcAddress(hPython, "PyRun_SimpleString");
    Py_Finalize_t Py_Finalize = (Py_Finalize_t)GetProcAddress(hPython, "Py_Finalize");

    if (Py_Initialize && PyRun_SimpleString && Py_Finalize) {
        Py_Initialize();

        int utf8_size = WideCharToMultiByte(CP_UTF8, 0, wsInstallPath.c_str(), -1, NULL, 0, NULL, NULL);
        std::string utf8Path(utf8_size, 0);
        WideCharToMultiByte(CP_UTF8, 0, wsInstallPath.c_str(), -1, &utf8Path[0], utf8_size, NULL, NULL);
        utf8Path.pop_back();

        std::string boot_script = 
            "import sys, os\n"
            "dir = r'" + utf8Path + "'\n"
            "sys.path.insert(0, dir)\n"
            "os.chdir(dir)\n"
            "sys.argv = ['Blur-main.py']\n"
            "__file__ = os.path.join(dir, 'Blur-main.py')\n"
            "with open('Blur-main.py', 'r', encoding='utf-8') as f:\n"
            "    code = compile(f.read(), __file__, 'exec')\n"
            "    exec(code, {'__name__': '__main__', '__file__': __file__})\n";

        PyRun_SimpleString(boot_script.c_str());
        Py_Finalize();
    }
    FreeLibrary(hPython);
}

// ==========================================
// 3. WinMain 入口
// ==========================================
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    HKEY hKey;
    wchar_t installPath[MAX_PATH] = { 0 };
    DWORD bufferSize = sizeof(installPath);
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\EyeSeeMore", 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
        RegQueryValueExW(hKey, L"InstallPath", NULL, NULL, (LPBYTE)installPath, &bufferSize);
        RegCloseKey(hKey);
    } else return 1;

    // B. 啟動 Python 背景執行緒 (注意這裡拿掉了 detach)
    std::thread pyThread(PythonThread, std::wstring(installPath));

    // C. 註冊並建立啟動畫面視窗
    const wchar_t CLASS_NAME[] = L"EyeSeeMoreSplash";
    WNDCLASSW wc = {};
    wc.lpfnWndProc = SplashWndProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = CLASS_NAME;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    RegisterClassW(&wc);

    int w = 450, h = 250;
    int x = (GetSystemMetrics(SM_CXSCREEN) - w) / 2;
    int y = (GetSystemMetrics(SM_CYSCREEN) - h) / 2;
    HWND hWnd = CreateWindowExW(WS_EX_TOPMOST, CLASS_NAME, L"Splash", WS_POPUP, x, y, w, h, NULL, NULL, hInstance, NULL);

    ShowWindow(hWnd, SW_SHOW);
    SetTimer(hWnd, 1, 100, NULL); 

    // D. 啟動畫面訊息迴圈
    MSG msg = {};
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    // ==========================================
    // E. 關鍵修復：等待 Python 執行緒結束
    // 當 Splash 畫面關閉後，主程式會在這裡默默等待，
    // 直到使用者關閉 EyeSeeMore 的 Python UI，整個程式才會乾淨地結束。
    // ==========================================
    if (pyThread.joinable()) {
        pyThread.join();
    }

    return 0;
}