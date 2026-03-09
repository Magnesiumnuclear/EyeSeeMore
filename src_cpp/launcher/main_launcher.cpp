#include <windows.h>
#include <string>

// 定義我們要從 python310.dll 偷接出來的函數指標
typedef void (*Py_Initialize_t)();
typedef int (*PyRun_SimpleString_t)(const char*);

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    
    // 1. 動態載入 Python 核心 DLL
    // 開發階段它會自動從您的系統 PATH 抓取；未來部署到 USB 時，只要把 python310.dll 放在旁邊就能隨插即用！
    HMODULE hPython = LoadLibraryW(L"C:\\Users\\samho\\AppData\\Local\\Programs\\Python\\Python310\\python310.dll");
    
    if (!hPython) {
        MessageBoxW(NULL, L"啟動失敗！找不到 python310.dll\n請確認 Python 已安裝，或 DLL 檔案與啟動器位於同目錄。", L"EyeSeeMore 環境錯誤", MB_ICONERROR);
        return 1;
    }

    // 2. 抓取 Python 啟動函數
    Py_Initialize_t Py_Initialize = (Py_Initialize_t)GetProcAddress(hPython, "Py_Initialize");
    PyRun_SimpleString_t PyRun_SimpleString = (PyRun_SimpleString_t)GetProcAddress(hPython, "PyRun_SimpleString");

    if (!Py_Initialize || !PyRun_SimpleString) {
        MessageBoxW(NULL, L"Python 引擎載入異常！", L"EyeSeeMore", MB_ICONERROR);
        return 1;
    }

    // 3. 喚醒 Python 引擎 (此時進程依然是 EyeSeeMore_Launcher.exe)
    Py_Initialize();

    // 4. 注入啟動腳本 (包含將 .venv-onnx 套件庫加入路徑，並具備錯誤彈窗防呆機制)
    const char* boot_script =
        "import sys\n"
        "import os\n"
        "sys.path.insert(0, os.path.abspath('.\\\\.venv-onnx\\\\Lib\\\\site-packages'))\n"
        "try:\n"
        "    with open('Blur-main.py', 'r', encoding='utf-8') as f:\n"
        "        code = f.read()\n"
        "    exec(code)\n"
        "except Exception as e:\n"
        "    import ctypes\n"
        "    ctypes.windll.user32.MessageBoxW(0, f'Python 執行崩潰:\\n{str(e)}', 'EyeSeeMore 嚴重錯誤', 0x10)\n";

    // 5. 執行 Blur-main.py
    PyRun_SimpleString(boot_script);

    return 0;
}