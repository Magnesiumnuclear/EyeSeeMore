#include <windows.h>
#include <iostream>
#include <string>

// --- 定義 Python 函數的指標型態 ---
typedef void (*Py_Initialize_t)(void);
typedef int (*PyRun_SimpleString_t)(const char*);
typedef void (*Py_Finalize_t)(void);

int main() {
    // 隱藏終端機黑窗 (正式版時開啟，測試時可先註解掉看報錯)
    // FreeConsole();

    // ==========================================
    // 1. 從註冊表讀取 EyeSeeMore 的安裝路徑
    // ==========================================
    HKEY hKey;
    wchar_t installPath[MAX_PATH] = { 0 };
    DWORD bufferSize = sizeof(installPath);
    
    // 開啟 HKCU\Software\EyeSeeMore
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\EyeSeeMore", 0, KEY_READ, &hKey) == ERROR_SUCCESS) {
        // 讀取 InstallPath 數值
        if (RegQueryValueExW(hKey, L"InstallPath", NULL, NULL, (LPBYTE)installPath, &bufferSize) != ERROR_SUCCESS) {
            MessageBoxW(NULL, L"找不到安裝路徑！請重新安裝 EyeSeeMore。", L"啟動錯誤", MB_ICONERROR);
            RegCloseKey(hKey);
            return 1;
        }
        RegCloseKey(hKey);
    } else {
        MessageBoxW(NULL, L"尚未安裝 EyeSeeMore！請先執行 Setup.exe。", L"啟動錯誤", MB_ICONERROR);
        return 1;
    }

    std::wstring wsInstallPath(installPath);

    // ==========================================
    // 2. 切換工作目錄到安裝路徑
    // ==========================================
    // 這一步極度重要！它確保 Python 腳本裡面的相對路徑 (如 models/ 或是 config.json) 都能正確對應
    SetCurrentDirectoryW(wsInstallPath.c_str());

    // ==========================================
    // 3. 組裝 python310.dll 的絕對路徑並載入
    // ==========================================
    std::wstring dllPath = wsInstallPath + L"\\python310.dll";
    HMODULE hPython = LoadLibraryW(dllPath.c_str());

    if (!hPython) {
        MessageBoxW(NULL, L"無法載入 AI 引擎 (python310.dll)！檔案可能遺失。", L"啟動錯誤", MB_ICONERROR);
        return 1;
    }

    // ==========================================
    // 4. 綁定 Python 函數並啟動
    // ==========================================
    Py_Initialize_t Py_Initialize = (Py_Initialize_t)GetProcAddress(hPython, "Py_Initialize");
    PyRun_SimpleString_t PyRun_SimpleString = (PyRun_SimpleString_t)GetProcAddress(hPython, "PyRun_SimpleString");
    Py_Finalize_t Py_Finalize = (Py_Finalize_t)GetProcAddress(hPython, "Py_Finalize");

    if (Py_Initialize && PyRun_SimpleString && Py_Finalize) {
        Py_Initialize();

        // [關鍵防護] 將 C++ 寬字元路徑轉為 UTF-8，以防使用者名稱有中文
        int utf8_size = WideCharToMultiByte(CP_UTF8, 0, wsInstallPath.c_str(), -1, NULL, 0, NULL, NULL);
        std::string utf8InstallPath(utf8_size, 0);
        WideCharToMultiByte(CP_UTF8, 0, wsInstallPath.c_str(), -1, &utf8InstallPath[0], utf8_size, NULL, NULL);
        utf8InstallPath.pop_back(); // 移除結尾的 null 字元

        // 啟動腳本：將安裝路徑加入 sys.path，然後執行 Blur-main.py
        std::string boot_script = 
            "import sys\n"
            "import os\n"
            "install_dir = r'" + utf8InstallPath + "'\n"
            "sys.path.insert(0, install_dir)\n"
            "os.chdir(install_dir)\n"
            "with open('Blur-main.py', 'r', encoding='utf-8') as f:\n"
            "    exec(f.read())\n";

        PyRun_SimpleString(boot_script.c_str());
        Py_Finalize();
    } else {
        MessageBoxW(NULL, L"AI 引擎核心函數綁定失敗！", L"啟動錯誤", MB_ICONERROR);
    }

    FreeLibrary(hPython);
    return 0;
}