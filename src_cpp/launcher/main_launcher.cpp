#include <windows.h>
#include <string>

typedef void (*Py_Initialize_t)();
typedef int (*PyRun_SimpleString_t)(const char*);

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    
    // ==========================================
    // [防彈裝甲] 獲取 .exe 自己所在的絕對路徑，並強制切換工作目錄
    // ==========================================
    wchar_t exePath[MAX_PATH];
    GetModuleFileNameW(NULL, exePath, MAX_PATH);
    std::wstring ws(exePath);
    std::wstring exeDir = ws.substr(0, ws.find_last_of(L"\\/"));
    SetCurrentDirectoryW(exeDir.c_str()); 

    // 1. 載入您電腦裡的 Python 核心
    HMODULE hPython = LoadLibraryW(L"C:\\Users\\samho\\AppData\\Local\\Programs\\Python\\Python310\\python310.dll");
    
    if (!hPython) {
        MessageBoxW(NULL, L"啟動失敗！找不到 python310.dll\n請確認 Python 已安裝，或 DLL 檔案與啟動器位於同目錄。", L"EyeSeeMore 環境錯誤", MB_ICONERROR);
        return 1;
    }

    // 2. 抓取 Python 啟動函數
    Py_Initialize_t Py_Initialize = (Py_Initialize_t)GetProcAddress(hPython, "Py_Initialize");
    PyRun_SimpleString_t PyRun_SimpleString = (PyRun_SimpleString_t)GetProcAddress(hPython, "PyRun_SimpleString");

    // 3. 喚醒 Python 引擎
    Py_Initialize();

    // 4. 注入啟動腳本 (加入字典定義，確保 __name__ == "__main__" 能正確觸發 PyQt6)
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

    // 5. 執行 Blur-main.py
    PyRun_SimpleString(boot_script);

    return 0;
}