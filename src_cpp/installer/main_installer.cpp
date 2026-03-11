#include <windows.h>
#include <iostream>
#include <string>

int main() {
    SetConsoleOutputCP(65001);
    std::cout << "[Setup] EyeSeeMore 安裝程式啟動..." << std::endl;

    // ==========================================
    // 1. 動態解析 %LOCALAPPDATA%\EyeSeeMore
    // ==========================================
    wchar_t expandedPath[MAX_PATH];
    ExpandEnvironmentStringsW(L"%LOCALAPPDATA%\\EyeSeeMore", expandedPath, MAX_PATH);
    std::wstring installDir = expandedPath;

    if (CreateDirectoryW(installDir.c_str(), NULL) || ERROR_ALREADY_EXISTS == GetLastError()) {
        std::cout << "[Setup] 安裝目錄準備就緒: " << std::string(installDir.begin(), installDir.end()) << std::endl;
    } else {
        std::cerr << "[Setup] 建立目錄失敗！" << std::endl;
        std::cin.get();
        return 1;
    }

    HKEY hKey;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, L"Software\\EyeSeeMore", 0, NULL, REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
        DWORD dataSize = (installDir.length() + 1) * sizeof(wchar_t);
        RegSetValueExW(hKey, L"InstallPath", 0, REG_SZ, (const BYTE*)installDir.c_str(), dataSize);
        RegCloseKey(hKey);
    }

    // ==========================================
    // 2. 尋找旁邊的 Payload.zip
    // ==========================================
    wchar_t exePath[MAX_PATH];
    GetModuleFileNameW(NULL, exePath, MAX_PATH);
    std::wstring wsExePath(exePath);
    // 取得 Setup.exe 目前所在的資料夾路徑
    std::wstring exeDir = wsExePath.substr(0, wsExePath.find_last_of(L"\\/"));
    std::wstring payloadPath = exeDir + L"\\Payload.zip";

    // 檢查 Payload.zip 是否存在
    if (GetFileAttributesW(payloadPath.c_str()) == INVALID_FILE_ATTRIBUTES) {
        std::cerr << "[Setup] 錯誤：找不到 Payload.zip！請確保安裝檔與資料包放在同一個資料夾。" << std::endl;
        std::cin.get();
        return 1;
    }

    // ==========================================
    // 3. 呼叫 Windows 內建 tar 直接解壓縮 (極速模式)
    // ==========================================
    std::cout << "[Setup] 發現資料包！正在解壓縮 AI 引擎與設定 (這可能需要幾分鐘)..." << std::endl;
    
    // 將工作目錄切換到目標安裝資料夾
    SetCurrentDirectoryW(installDir.c_str());
    
    // 組裝指令：tar -xf "D:\...\Payload.zip"
    // 加上雙引號以防路徑中有空白
    std::wstring tarCmd = L"tar -xf \"" + payloadPath + L"\"";
    
    int result = _wsystem(tarCmd.c_str());
    
    if (result == 0) {
        std::cout << "[Setup] 安裝成功！您的 AI 引擎已佈署完畢。" << std::endl;
    } else {
        std::cerr << "[Setup] 解壓縮失敗！錯誤碼: " << result << std::endl;
    }

    std::cout << "\n[Setup] EyeSeeMore 已安裝完畢！請按 Enter 鍵離開..." << std::endl;
    std::cin.get();
    return 0;
}