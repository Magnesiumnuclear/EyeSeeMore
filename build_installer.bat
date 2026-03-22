@echo off
chcp 65001 > nul
echo ===================================================
echo [系統] 正在編譯 EyeSeeMore 專案 (包含應用程式圖示)...
echo ===================================================

REM 檢查並建立 build 資料夾
set BUILD_DIR=build
if not exist "%BUILD_DIR%" (
    echo [系統] 建立 build 資料夾...
    mkdir "%BUILD_DIR%"
)

echo.
echo [0/2] 正在編譯程式圖示資源 (resource.rc) ...
REM 使用 windres 將 .rc 與 .ico 轉換為 g++ 看得懂的 .res 檔案
windres src_cpp/resources/resource.rc -O coff -o "%BUILD_DIR%\app_icon.res"
if %errorlevel% neq 0 (
    echo [錯誤] 圖示資源編譯失敗！請檢查 src_cpp/resources 裡是否有 ico 圖片。
    pause
    exit /b
)

echo.
echo [1/2] 正在編譯啟動器 (EyeSeeMore_Launcher.exe) ...
REM 注意這裡加入了 "%BUILD_DIR%\app_icon.res" 讓它把圖示吃進去
g++ src_cpp/launcher/main_launcher.cpp "%BUILD_DIR%\app_icon.res" -o "%BUILD_DIR%\EyeSeeMore_Launcher.exe" -static -static-libgcc -static-libstdc++ -mwindows
if %errorlevel% neq 0 (
    echo [錯誤] 啟動器編譯失敗！請檢查程式碼。
    pause
    exit /b
)

echo.
echo [2/2] 正在編譯安裝程式 (EyeSeeMore_Setup.exe) ...
REM 同樣加入 "%BUILD_DIR%\app_icon.res"
g++ src_cpp/installer/main_installer.cpp "%BUILD_DIR%\app_icon.res" -o "%BUILD_DIR%\EyeSeeMore_Setup.exe" -static -static-libgcc -static-libstdc++ -lole32 -luuid
if %errorlevel% neq 0 (
    echo [錯誤] 安裝程式編譯失敗！請檢查程式碼。
    pause
    exit /b
)

echo.
echo ===================================================
echo [成功] 🎉 兩個檔案皆已順利編譯，且已掛載專屬圖示！
echo [位置] %~dp0%BUILD_DIR%\
echo ===================================================
pause