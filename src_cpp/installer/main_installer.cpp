#include <windows.h>
#include <iostream>
#include <string>
#include <thread>
#include <atomic>
#include <shobjidl.h> // 建立捷徑需要
#include <shlobj.h>   // 獲取桌面路徑需要

// ==========================================
// 1. 建立桌面捷徑的專用函數 (使用 Windows COM 介面)
// ==========================================
bool CreateDesktopShortcut(const std::wstring& targetExePath, const std::wstring& shortcutName) {
    HRESULT hres = CoInitialize(NULL);
    if (FAILED(hres)) return false;

    bool result = false;
    IShellLinkW* psl;
    if (SUCCEEDED(CoCreateInstance(CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER, IID_IShellLinkW, (LPVOID*)&psl))) {
        psl->SetPath(targetExePath.c_str());
        
        std::wstring workDir = targetExePath.substr(0, targetExePath.find_last_of(L"\\/"));
        psl->SetWorkingDirectory(workDir.c_str());

        IPersistFile* ppf;
        if (SUCCEEDED(psl->QueryInterface(IID_IPersistFile, (LPVOID*)&ppf))) {
            wchar_t desktopPath[MAX_PATH];
            if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, desktopPath))) {
                std::wstring linkPath = std::wstring(desktopPath) + L"\\" + shortcutName + L".lnk";
                if (SUCCEEDED(ppf->Save(linkPath.c_str(), TRUE))) {
                    result = true;
                }
            }
            ppf->Release();
        }
        psl->Release();
    }
    CoUninitialize();
    return result;
}

// ==========================================
// 2. 模組化的解壓縮與進度條繪製函數
// ==========================================
bool ExtractZipWithProgress(const std::wstring& zipPath, const std::wstring& installDir, const std::string& stageMessage) {
    SetCurrentDirectoryW(installDir.c_str());
    std::wstring tarCmd = L"tar -xf \"" + zipPath + L"\"";

    std::atomic<bool> isExtracting(true);
    std::atomic<int> extractResult(-1);

    // [背景執行緒] 負責解壓縮
    std::thread extractThread([&]() {
        extractResult = _wsystem(tarCmd.c_str());
        isExtracting = false; 
    });

    // [主執行緒] 負責畫進度條
    const char* spinner = "|/-\\";
    int spinIdx = 0;
    int secondsElapsed = 0;
    
    while (isExtracting) {
        std::cout << "\r" << stageMessage << " " << spinner[spinIdx++ % 4] 
                  << " (已耗時: " << secondsElapsed / 10 << " 秒)   " << std::flush;
        Sleep(100);
        secondsElapsed++;
    }
    
    extractThread.join();
    std::cout << "\n"; // 換行保留歷史紀錄

    if (extractResult == 0) {
        std::cout << " -> 佈署成功！\n" << std::endl;
        return true;
    } else {
        std::cerr << " -> [錯誤] 解壓縮失敗！錯誤碼: " << extractResult << std::endl;
        return false;
    }
}

// ==========================================
// 3. 主程式入口
// ==========================================
int main() {
    SetConsoleOutputCP(65001);
    std::cout << "=============================================" << std::endl;
    std::cout << "      EyeSeeMore AI Vision Engine 安裝程式     " << std::endl;
    std::cout << "=============================================\n" << std::endl;

    // A. 動態解析 %LOCALAPPDATA%\EyeSeeMore
    wchar_t expandedPath[MAX_PATH];
    ExpandEnvironmentStringsW(L"%LOCALAPPDATA%\\EyeSeeMore", expandedPath, MAX_PATH);
    std::wstring installDir = expandedPath;

    if (CreateDirectoryW(installDir.c_str(), NULL) || ERROR_ALREADY_EXISTS == GetLastError()) {
        std::cout << "[系統] 安裝目錄準備就緒: " << std::string(installDir.begin(), installDir.end()) << std::endl;
    } else {
        std::cerr << "[系統] 建立目錄失敗！" << std::endl;
        std::cin.get();
        return 1;
    }

    // B. 寫入註冊表
    HKEY hKey;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, L"Software\\EyeSeeMore", 0, NULL, REG_OPTION_NON_VOLATILE, KEY_WRITE, NULL, &hKey, NULL) == ERROR_SUCCESS) {
        DWORD dataSize = (installDir.length() + 1) * sizeof(wchar_t);
        RegSetValueExW(hKey, L"InstallPath", 0, REG_SZ, (const BYTE*)installDir.c_str(), dataSize);
        RegCloseKey(hKey);
    }

    // C. 尋找三個模組化 ZIP 檔案
    wchar_t exePath[MAX_PATH];
    GetModuleFileNameW(NULL, exePath, MAX_PATH);
    std::wstring wsExePath(exePath);
    std::wstring exeDir = wsExePath.substr(0, wsExePath.find_last_of(L"\\/"));
    
    std::wstring appZip = exeDir + L"\\App_Code.zip";
    std::wstring runtimeZip = exeDir + L"\\Runtime.zip";
    std::wstring modelsZip = exeDir + L"\\AI_Models.zip";

    // 嚴格檢查三個檔案是否都存在
    if (GetFileAttributesW(appZip.c_str()) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(runtimeZip.c_str()) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(modelsZip.c_str()) == INVALID_FILE_ATTRIBUTES) {
        std::cerr << "\n[錯誤] 找不到完整的安裝資料夾！" << std::endl;
        std::cerr << "請確保 App_Code.zip, Runtime.zip, 與 AI_Models.zip 皆放在安裝檔旁邊。" << std::endl;
        std::cin.get();
        return 1;
    }

    std::cout << "[系統] 檔案檢查完畢，開始進行三階段佈署...\n" << std::endl;

    // ==========================================
    // D. 依序執行多段式解壓縮
    // ==========================================
    if (!ExtractZipWithProgress(appZip, installDir, "[Step 1/3] 正在佈署主程式核心...")) {
        std::cin.get(); return 1;
    }
    
    if (!ExtractZipWithProgress(runtimeZip, installDir, "[Step 2/3] 正在準備執行環境...")) {
        std::cin.get(); return 1;
    }
    
    if (!ExtractZipWithProgress(modelsZip, installDir, "[Step 3/3] 正在安裝 AI 大腦 (檔案極大，請耐心等候)...")) {
        std::cin.get(); return 1;
    }

    // ==========================================
    // E. 建立桌面捷徑
    // ==========================================
    std::cout << "[系統] 正在建立桌面捷徑..." << std::endl;
    std::wstring launcherPath = installDir + L"\\EyeSeeMore_Launcher.exe";
    
    if (GetFileAttributesW(launcherPath.c_str()) != INVALID_FILE_ATTRIBUTES) {
        if (CreateDesktopShortcut(launcherPath, L"EyeSeeMore")) {
            std::cout << "[系統] 捷徑建立成功！" << std::endl;
        } else {
            std::cerr << "[系統] 警告：桌面捷徑建立失敗。" << std::endl;
        }
    } else {
        std::cerr << "[系統] 警告：找不到啟動器，無法建立捷徑。" << std::endl;
    }

    std::cout << "\n=============================================" << std::endl;
    std::cout << " EyeSeeMore 已經完美安裝在您的電腦上！" << std::endl;
    std::cout << " 請直接雙擊桌面的捷徑開始使用。" << std::endl;
    std::cout << "=============================================\n" << std::endl;

    std::cout << "請按 Enter 鍵離開..." << std::endl;
    std::cin.get();
    return 0;
}