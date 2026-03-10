#include <windows.h>
#include <string>
#include <thread>
#include <atomic>
#include <shobjidl.h> // ITaskbarList3 介面

// Python 函數指標
typedef void (*Py_Initialize_t)();
typedef int (*PyRun_SimpleString_t)(const char*);

// 全域變數
HWND g_hSplashWnd = NULL;
std::atomic<bool> g_PythonFailed(false);

// ==========================================
// [背景執行緒] 專門負責吞下 Python 引擎與執行程式
// ==========================================
void PythonWorkerThread(std::wstring exeDir) {
    SetCurrentDirectoryW(exeDir.c_str()); 

    // 載入 Python 核心 (保留您電腦的路徑)
    HMODULE hPython = LoadLibraryW(L"C:\\Users\\samho\\AppData\\Local\\Programs\\Python\\Python310\\python310.dll");
    
    if (!hPython) {
        g_PythonFailed = true;
        MessageBoxW(NULL, L"啟動失敗！找不到 python310.dll", L"EyeSeeMore 環境錯誤", MB_ICONERROR);
        PostMessage(g_hSplashWnd, WM_CLOSE, 0, 0);
        return;
    }

    Py_Initialize_t Py_Initialize = (Py_Initialize_t)GetProcAddress(hPython, "Py_Initialize");
    PyRun_SimpleString_t PyRun_SimpleString = (PyRun_SimpleString_t)GetProcAddress(hPython, "PyRun_SimpleString");

    Py_Initialize();

    const char* boot_script =
        "import sys\n"
        "import os\n"
        "sys.path.insert(0, os.path.abspath('.\\\\.venv-onnx\\\\Lib\\\\site-packages'))\n"
        "try:\n"
        "    with open('Blur-main.py', 'r', encoding='utf-8') as f:\n"
        "        code = f.read()\n"
        "    exec(code, {'__name__': '__main__', '__file__': 'Blur-main.py'})\n"
        "except Exception as e:\n"
        "    import ctypes\n"
        "    ctypes.windll.user32.MessageBoxW(0, f'Python 執行崩潰:\\n{str(e)}', 'EyeSeeMore 嚴重錯誤', 0x10)\n";

    // 執行 Python (這行會一直卡住，直到 Blur-main.py 視窗被關閉)
    PyRun_SimpleString(boot_script);

    // 當 Python 視窗關閉，也就是使用者退出軟體時，連帶關閉背景的 C++
    PostMessage(g_hSplashWnd, WM_CLOSE, 0, 0);
}

// ==========================================
// [主執行緒] Splash 視窗繪圖與交接管理
// ==========================================
LRESULT CALLBACK SplashWndProc(HWND hwnd, UINT uMsg, WPARAM wParam, LPARAM lParam) {
    switch (uMsg) {
        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC hdc = BeginPaint(hwnd, &ps);
            
            // 1. 畫背景：深灰色 (#1e1e1e)
            HBRUSH hBrush = CreateSolidBrush(RGB(30, 30, 30));
            FillRect(hdc, &ps.rcPaint, hBrush);
            DeleteObject(hBrush);

            // 2. 畫邊框：稍亮的灰色
            HBRUSH hBorder = CreateSolidBrush(RGB(70, 70, 70));
            FrameRect(hdc, &ps.rcPaint, hBorder);
            DeleteObject(hBorder);

            // 3. 畫文字：EyeSeeMore Logo (Win11 藍色)
            SetBkMode(hdc, TRANSPARENT);
            SetTextColor(hdc, RGB(96, 205, 255)); // #60cdff
            HFONT hFontTitle = CreateFontW(32, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
            SelectObject(hdc, hFontTitle);
            RECT textRect; GetClientRect(hwnd, &textRect);
            textRect.top -= 20; // 稍微往上移
            DrawTextW(hdc, L"EyeSeeMore", -1, &textRect, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
            DeleteObject(hFontTitle);

            // 4. 畫文字：載入狀態 (灰色)
            SetTextColor(hdc, RGB(150, 150, 150));
            HFONT hFontSub = CreateFontW(14, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
            SelectObject(hdc, hFontSub);
            GetClientRect(hwnd, &textRect);
            textRect.top += 60; // 往下移
            DrawTextW(hdc, L"Initializing AI Engine & Python...", -1, &textRect, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
            DeleteObject(hFontSub);

            EndPaint(hwnd, &ps);
            return 0;
        }
        case WM_TIMER: {
            // 每 100 毫秒檢查一次：PyQt6 的主視窗畫出來了嗎？
            HWND hPyQtWnd = FindWindowW(NULL, L"EyeSeeMore-(Alpha)");
            if (hPyQtWnd != NULL) {
                // 發現主視窗！交接完成，把 Splash 視窗隱藏
                ShowWindow(hwnd, SW_HIDE);
                KillTimer(hwnd, 1);
            }
            return 0;
        }
        case WM_DESTROY:
            PostQuitMessage(0);
            return 0;
    }
    return DefWindowProc(hwnd, uMsg, wParam, lParam);
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    // 1. 初始化 COM (為了工具列進度條)
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);

    // 2. 註冊並建立無邊框 Splash 視窗
    const wchar_t CLASS_NAME[] = L"SplashWindowClass";
    WNDCLASSW wc = { };
    wc.lpfnWndProc = SplashWndProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = CLASS_NAME;
    RegisterClassW(&wc);

    int width = 360;
    int height = 160;
    int screenW = GetSystemMetrics(SM_CXSCREEN);
    int screenH = GetSystemMetrics(SM_CYSCREEN);

    // 建立置中、無邊框 (WS_POPUP) 視窗
    g_hSplashWnd = CreateWindowExW(
        WS_EX_APPWINDOW, CLASS_NAME, L"EyeSeeMore Launcher", 
        WS_POPUP | WS_VISIBLE,
        (screenW - width) / 2, (screenH - height) / 2, width, height,
        NULL, NULL, hInstance, NULL
    );

    // 3. 強制在工具列顯示「左右跑動」的載入動畫 (Indeterminate)
    ITaskbarList3* pTaskbar = NULL;
    if (SUCCEEDED(CoCreateInstance(CLSID_TaskbarList, NULL, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&pTaskbar)))) {
        pTaskbar->SetProgressState(g_hSplashWnd, TBPF_INDETERMINATE);
    }

    // 4. 啟動交接監視器 (每 100ms 檢查一次 PyQt 是否出現)
    SetTimer(g_hSplashWnd, 1, 100, NULL);

    // 5. 獲取路徑並啟動背景 Python 執行緒
    wchar_t exePath[MAX_PATH];
    GetModuleFileNameW(NULL, exePath, MAX_PATH);
    std::wstring ws(exePath);
    std::wstring exeDir = ws.substr(0, ws.find_last_of(L"\\/"));

    std::thread pythonThread(PythonWorkerThread, exeDir);
    pythonThread.detach(); // 讓它在背景自由奔跑

    // 6. 維持視窗不卡死的 Message Loop
    MSG msg = { };
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    if (pTaskbar) pTaskbar->Release();
    CoUninitialize();

    return 0;
}