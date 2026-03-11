#include <windows.h>
#include <iostream>
#include <string>

int main() {
    // 為了讓終端機能正確顯示中文
    SetConsoleOutputCP(65001);
    std::cout << "[Setup] EyeSeeMore 安裝程式啟動..." << std::endl;

    // ==========================================
    // 1. 動態解析 %LOCALAPPDATA%\EyeSeeMore 路徑
    // ==========================================
    wchar_t expandedPath[MAX_PATH];
    // 使用 Windows API 自動將 %LOCALAPPDATA% 轉換為 C:\Users\您的名字\AppData\Local
    ExpandEnvironmentStringsW(L"%LOCALAPPDATA%\\EyeSeeMore", expandedPath, MAX_PATH);
    std::wstring installDir = expandedPath;

    std::wcout << L"[Setup] 目標安裝路徑為: " << installDir << std::endl;

    // ==========================================
    // 2. 建立實體資料夾
    // ==========================================
    // 如果資料夾不存在就建立，如果已存在就略過
    if (CreateDirectoryW(installDir.c_str(), NULL) || ERROR_ALREADY_EXISTS == GetLastError()) {
        std::cout << "[Setup] 實體資料夾準備就緒。" << std::endl;
    } else {
        std::cerr << "[Setup] 警告：無法建立實體資料夾，錯誤碼: " << GetLastError() << std::endl;
    }

    // ==========================================
    // 3. 寫入註冊表
    // ==========================================
    HKEY hKey;
    LSTATUS status = RegCreateKeyExW(
        HKEY_CURRENT_USER,         // 依然寫入目前使用者層級，免管理員權限
        L"Software\\EyeSeeMore", 
        0, NULL, REG_OPTION_NON_VOLATILE, 
        KEY_WRITE, 
        NULL, &hKey, NULL
    );

    if (status == ERROR_SUCCESS) {
        DWORD dataSize = (installDir.length() + 1) * sizeof(wchar_t);
        
        status = RegSetValueExW(
            hKey, 
            L"InstallPath",        // 寫入數值名稱
            0, 
            REG_SZ, 
            (const BYTE*)installDir.c_str(), 
            dataSize
        );

        if (status == ERROR_SUCCESS) {
            std::cout << "[Setup] 註冊表寫入成功！系統已記錄 EyeSeeMore 的位置。" << std::endl;
        } else {
            std::cerr << "[Setup] 寫入數值失敗，Windows 錯誤碼: " << status << std::endl;
        }

        RegCloseKey(hKey);
    } else {
        std::cerr << "[Setup] 建立或開啟機碼失敗，Windows 錯誤碼: " << status << std::endl;
    }

    std::cout << "\n[Setup] 安裝地基建立完畢！請按 Enter 鍵離開..." << std::endl;
    std::cin.get();
    return 0;
}