#include <windows.h>
#include <string>

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    
    // 定義 Python 路徑與主程式
    std::wstring command = L".\\.venv-onnx\\Scripts\\pythonw.exe Blur-main.py";

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    // 隱藏視窗
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;

    // 呼叫 API
    BOOL success = CreateProcessW(
        NULL, &command[0], NULL, NULL, FALSE, 
        CREATE_NO_WINDOW, NULL, NULL, &si, &pi
    );

    if (success) {
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    } else {
        // [關鍵防呆] 如果啟動失敗，抓取系統錯誤碼並彈出視窗警告！
        DWORD errorCode = GetLastError();
        std::wstring errorMsg = L"啟動失敗！\n找不到 Python 環境或 Blur-main.py。\n系統錯誤碼: " + std::to_wstring(errorCode);
        
        MessageBoxW(NULL, errorMsg.c_str(), L"EyeSeeMore 啟動錯誤", MB_ICONERROR | MB_OK);
    }

    return 0;
}