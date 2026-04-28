@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

:: =====================================================
::  EyeSeeMore – 一鍵編譯 + 發佈打包腳本
::  執行順序：C++ 編譯 → 呼叫 pack_release.py 打包
:: =====================================================

:: 切換到腳本所在目錄（專案根目錄），確保所有相對路徑正確
cd /d "%~dp0"

set BUILD_DIR=build
set LAUNCHER_SRC=src_cpp/launcher/main_launcher.cpp
set INSTALLER_SRC=src_cpp/installer/main_installer.cpp
set RESOURCE_RC=src_cpp/resources/resource.rc
set PACK_SCRIPT=pack_release.py

echo.
echo =====================================================
echo  [EyeSeeMore Build Pipeline]
echo =====================================================

:: ── 建立 build 暫存資料夾 ──────────────────────────────
if not exist "%BUILD_DIR%" (
    echo [Step 0] 建立 build\ 暫存資料夾...
    mkdir "%BUILD_DIR%"
)

:: ── Stage 0: 編譯圖示資源 ──────────────────────────────
echo.
echo [0/3] 正在編譯程式圖示資源 (resource.rc) ...
windres "%RESOURCE_RC%" -O coff -o "%BUILD_DIR%\app_icon.res"
if %errorlevel% neq 0 (
    echo.
    echo [錯誤] 圖示資源編譯失敗！請確認 src_cpp/resources/ 有 .ico 圖片且 windres 在 PATH 中。
    goto :fail
)
echo   ^> app_icon.res 編譯成功

:: ── Stage 1: 編譯 Launcher ─────────────────────────────
echo.
echo [1/3] 正在編譯啟動器 (EyeSeeMore_Launcher.exe) ...
g++ "%LAUNCHER_SRC%" "%BUILD_DIR%\app_icon.res" ^
    -o "%BUILD_DIR%\EyeSeeMore_Launcher.exe" ^
    -static -static-libgcc -static-libstdc++ ^
    -mwindows
if %errorlevel% neq 0 (
    echo.
    echo [錯誤] Launcher 編譯失敗！
    goto :fail
)
echo   ^> EyeSeeMore_Launcher.exe 編譯成功

:: ── Stage 2: 編譯 Installer ────────────────────────────
echo.
echo [2/3] 正在編譯安裝程式 (EyeSeeMore_Setup.exe) ...
g++ "%INSTALLER_SRC%" "%BUILD_DIR%\app_icon.res" ^
    -o "%BUILD_DIR%\EyeSeeMore_Setup.exe" ^
    -static -static-libgcc -static-libstdc++ ^
    -lole32 -luuid -lshell32
if %errorlevel% neq 0 (
    echo.
    echo [錯誤] Setup 編譯失敗！
    goto :fail
)
echo   ^> EyeSeeMore_Setup.exe 編譯成功

:: ── Stage 3: 打包發佈套件 ──────────────────────────────
echo.
echo [3/3] 正在執行發佈打包腳本 (pack_release.py) ...
echo.

:: 搜尋可用的 Python 直譯器（優先使用 .venv\Scripts\python.exe）
set PYTHON_EXE=
if exist ".venv\Scripts\python.exe" (
    set PYTHON_EXE=.venv\Scripts\python.exe
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        set PYTHON_EXE=python
    ) else (
        where python3 >nul 2>&1
        if !errorlevel! equ 0 (
            set PYTHON_EXE=python3
        )
    )
)

if "!PYTHON_EXE!"=="" (
    echo [錯誤] 找不到 Python！請確認 Python 已安裝或 .venv 已建立。
    goto :fail
)

echo   使用直譯器：!PYTHON_EXE!
echo.
set PYTHONIOENCODING=utf-8
:: %~dp0 尾端帶有反斜線，直接放進引號會導致 \" 跳脫閉合引號，造成路徑解析錯誤
:: 解法：先去掉尾端的反斜線再傳入
set "_ROOT=%~dp0"
set "_ROOT=!_ROOT:~0,-1!"
"!PYTHON_EXE!" "%PACK_SCRIPT%" "!_ROOT!" "%BUILD_DIR%"
if %errorlevel% neq 0 (
    echo.
    echo [錯誤] 發佈打包失敗！請查看上方的錯誤訊息。
    goto :fail
)

:: ── 成功結尾 ───────────────────────────────────────────
echo.
echo =====================================================
echo  ^>^> Build Pipeline 完成！
echo  ^>^> 發佈目錄：%~dp0EyeSeeMore_installer\
echo =====================================================
pause
exit /b 0

:fail
echo.
echo =====================================================
echo  ^>^> Build Pipeline 中止（見上方錯誤）
echo =====================================================
pause
exit /b 1
