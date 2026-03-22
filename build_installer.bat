@echo off
chcp 65001 > nul
echo ===================================================
echo [系統] 正在編譯 EyeSeeMore 專案...
echo ===================================================

REM 1. 檢查並自動建立 build 資料夾 (如果不存在的話)
set BUILD_DIR=build
if not exist "%BUILD_DIR%" (
    echo [系統] 偵測到沒有 build 資料夾，正在為您建立...
    mkdir "%BUILD_DIR%"
)

echo.
echo [1/2] 正在編譯啟動器，並輸出至 %BUILD_DIR%\EyeSeeMore_Launcher.exe ...
REM 將輸出路徑指定到 build 資料夾下 (舊檔案會自動被覆蓋)
g++ src_cpp/launcher/main_launcher.cpp -o "%BUILD_DIR%\EyeSeeMore_Launcher.exe" -static -static-libgcc -static-libstdc++ -mwindows
if %errorlevel% neq 0 (
    echo [錯誤] 啟動器編譯失敗！請檢查程式碼。
    pause
    exit /b
)

echo.
echo [2/2] 正在編譯安裝程式，並輸出至 %BUILD_DIR%\EyeSeeMore_Setup.exe ...
REM 同樣將輸出路徑指定到 build 資料夾下
g++ src_cpp/installer/main_installer.cpp -o "%BUILD_DIR%\EyeSeeMore_Setup.exe" -static -static-libgcc -static-libstdc++ -lole32 -luuid
if %errorlevel% neq 0 (
    echo [錯誤] 安裝程式編譯失敗！請檢查程式碼。
    pause
    exit /b
)

echo.
echo ===================================================
echo [成功] 🎉 兩個檔案皆已順利編譯！
echo [位置] D:\software\Gemini\rag-image\build\
echo        (若原本有舊檔案，已為您自動覆蓋更新)
echo ===================================================
pause