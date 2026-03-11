#include <windows.h>
#include <iostream>
#include <string>
#include <thread>
#include <atomic>
#include <shobjidl.h> // 建立捷徑需要
#include <shlobj.h>   // 獲取桌面路徑需要

// ==========================================
// 建立桌面捷徑的專用函數 (使用 Windows COM 介面)
// ==========================================
bool CreateDesktopShortcut(const std::wstring& targetExePath, const std::wstring& shortcutName) {
    HRESULT hres = CoInitialize(NULL);
    if (FAILED(hres)) return false;

    bool result = false;
    IShellLinkW* psl;
    // 呼叫 COM 建立捷徑物件
    if (SUCCEEDED(CoCreateInstance(CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER, IID_IShellLinkW, (LPVOID*)&psl))) {
        psl->SetPath(targetExePath.c_str());
        
        // 設定工作目錄為 exe 所在的資料夾
        std::wstring workDir = targetExePath.substr(0, targetExePath.find_last_of(L"\\/"));
        psl->SetWorkingDirectory(workDir.c_str());

        IPersistFile* ppf;
        if (SUCCEEDED(psl->QueryInterface(IID_IPersistFile, (LPVOID*)&ppf))) {
            wchar_t desktopPath[MAX_PATH];
            // 自動獲取目前使用者的「桌面」路徑
            if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, desktopPath))) {
                std::wstring linkPath = std::wstring(desktopPath) + L"\\" + shortcutName + L".lnk";
                if (SUCCEEDED(ppf->Save(linkPath.c_str(), TRUE))) {
                    result = true; // 儲存捷徑成功
                }
            }
            ppf->Release();
        }
        psl->Release();
    }
    CoUninitialize();
    return result;
}

int main() {
    SetConsoleOutputCP(65001);
    std::cout << "[Setup] EyeSeeMore 安裝程式啟動..." << std::endl;

    // 1. 動態解析 %LOCALAPPDATA%\EyeSeeMore
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

    // 寫入註冊表
    HKEY hKey;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, L"Software\\EyeSeeMore", 0, NULL, REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
        DWORD dataSize = (installDir.length() + 1) * sizeof(wchar_t);
        RegSetValueExW(hKey, L"InstallPath", 0, REG_SZ, (const BYTE*)installDir.c_str(), dataSize);
        RegCloseKey(hKey);
    }

    // 2. 尋找旁邊的 Payload.zip
    wchar_t exePath[MAX_PATH];
    GetModuleFileNameW(NULL, exePath, MAX_PATH);
    std::wstring wsExePath(exePath);
    std::wstring exeDir = wsExePath.substr(0, wsExePath.find_last_of(L"\\/"));
    std::wstring payloadPath = exeDir + L"\\Payload.zip";

    if (GetFileAttributesW(payloadPath.c_str()) == INVALID_FILE_ATTRIBUTES) {
        std::cerr << "[Setup] 錯誤：找不到 Payload.zip！" << std::endl;
        std::cin.get();
        return 1;
    }

    // ==========================================
    // 3. 多執行緒解壓縮與動態進度條
    // ==========================================
    SetCurrentDirectoryW(installDir.c_str());
    std::wstring tarCmd = L"tar -xf \"" + payloadPath + L"\"";
    
    // 使用 atomic 變數讓兩個執行緒安全溝通
    std::atomic<bool> isExtracting(true);
    std::atomic<int> extractResult(-1);

    // [背景執行緒] 負責吃力的解壓縮工作
    std::thread extractThread([&]() {
        extractResult = _wsystem(tarCmd.c_str());
        isExtracting = false; // 解壓完成，通知主執行緒
    });

    // [主執行緒] 負責畫面的動態進度條
    const char* spinner = "|/-\\";
    int spinIdx = 0;
    int secondsElapsed = 0;
    
    while (isExtracting) {
        std::cout << "\r[Setup] 正在解壓縮 AI 引擎與設定包... " << spinner[spinIdx++ % 4] 
                  << " (已耗時: " << secondsElapsed / 10 << " 秒)   " << std::flush;
        Sleep(100); // 每 0.1 秒轉一次
        secondsElapsed++;
    }
    
    // 等待背景執行緒完美收尾
    extractThread.join();
    std::cout << "\n"; // 換行，避免蓋掉進度條

    if (extractResult == 0) {
        std::cout << "[Setup] 檔案釋放成功！" << std::endl;
        
        // ==========================================
        // 4. 建立桌面捷徑
        // ==========================================
        std::cout << "[Setup] 正在建立桌面捷徑..." << std::endl;
        std::wstring launcherPath = installDir + L"\\EyeSeeMore_Launcher.exe";
        
        // 確保 Launcher 真的有被解壓縮出來
        if (GetFileAttributesW(launcherPath.c_str()) != INVALID_FILE_ATTRIBUTES) {
            if (CreateDesktopShortcut(launcherPath, L"EyeSeeMore")) {
                std::cout << "[Setup] 捷徑建立成功！" << std::endl;
            } else {
                std::cerr << "[Setup] 警告：桌面捷徑建立失敗。" << std::endl;
            }
        } else {
            std::cerr << "[Setup] 警告：在安裝包內找不到 EyeSeeMore_Launcher.exe，無法建立捷徑。" << std::endl;
        }

        std::cout << "\n=============================================" << std::endl;
        std::cout << " 🎉 EyeSeeMore 已經完美安裝在您的電腦上！" << std::endl;
        std::cout << " 請直接雙擊桌面的捷徑開始使用。" << std::endl;
        std::cout << "=============================================\n" << std::endl;

    } else {
        std::cerr << "[Setup] 解壓縮失敗！錯誤碼: " << extractResult << std::endl;
    }

    std::cout << "[Setup] 請按 Enter 鍵離開..." << std::endl;
    std::cin.get();
    return 0;
}