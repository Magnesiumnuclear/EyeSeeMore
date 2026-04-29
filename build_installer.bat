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

:: ── 前置檢查：User_Environment 是否存在 ──────────────────
echo.
if not exist "User_Environment\" (
    echo [警告] 找不到 User_Environment\ 資料夾！
    echo        Runtime.zip 將無法打包，請確認已放置 Portable Python 環境。
    echo.
    pause
) else (
    echo [OK] User_Environment\ 已找到。
    echo.
    :: ── 詢問是否執行 fix_env.py ────────────────────────────
    if exist "fix_env.py" (
        set /p "_RUN_FIX=是否執行 fix_env.py 檢查套件完整性再開始編譯？ [Y/n] "
        if /I "!_RUN_FIX!"=="" set _RUN_FIX=Y
        if /I "!_RUN_FIX!"=="y" (
            echo.
            echo [環境修復] 正在執行 fix_env.py --yes ...
            echo.
            :: 優先使用 User_Environment 內的 python 執行 fix_env.py
            if exist "User_Environment\python.exe" (
                "User_Environment\python.exe" fix_env.py --yes
            ) else (
                python fix_env.py --yes
            )
            if %errorlevel% neq 0 (
                echo.
                echo [錯誤] fix_env.py 執行失敗，請手動修正環境後再繼續。
                pause
                exit /b 1
            )
            echo.
            echo [OK] 環境修復完成，繼續建置流程...
            echo.
        ) else (
            echo [略過] 跳過環境檢查。
            echo.
        )
    ) else (
        echo [略過] 找不到 fix_env.py，跳過環境檢查。
        echo.
    )
)
set LAUNCHER_SRC=src_cpp/launcher/main_launcher.cpp
set INSTALLER_SRC=src_cpp/installer/main_installer.cpp
set RESOURCE_RC=src_cpp/resources/resource.rc
set PACK_SCRIPT=pack_release.py

echo.
echo =====================================================
echo  [EyeSeeMore Build Pipeline]
echo =====================================================
echo.
call :DrawBar 0  "初始化..."
echo.

:: ── 建立 build 暫存資料夾 ──────────────────────────────
if not exist "%BUILD_DIR%" (
    echo [Step 0] 建立 build\ 暫存資料夾...
    mkdir "%BUILD_DIR%"
)

:: ── Stage 0: 編譯圖示資源 (0 %% → 25 %%) ──────────────
echo.
echo [1/4] 正在編譯程式圖示資源 (resource.rc) ...
windres "%RESOURCE_RC%" -O coff -o "%BUILD_DIR%\app_icon.res"
if %errorlevel% neq 0 (
    echo.
    echo [錯誤] 圖示資源編譯失敗！請確認 src_cpp/resources/ 有 .ico 圖片且 windres 在 PATH 中。
    goto :fail
)
call :DrawBar 25 "resource.rc  → app_icon.res [OK]"

:: ── Stage 1: 編譯 Launcher (25 %% → 50 %%) ────────────
echo.
echo [2/4] 正在編譯啟動器 (EyeSeeMore_Launcher.exe) ...
g++ "%LAUNCHER_SRC%" "%BUILD_DIR%\app_icon.res" ^
    -o "%BUILD_DIR%\EyeSeeMore_Launcher.exe" ^
    -static -static-libgcc -static-libstdc++ ^
    -mwindows
if %errorlevel% neq 0 (
    echo.
    echo [錯誤] Launcher 編譯失敗！
    goto :fail
)
call :DrawBar 50 "main_launcher.cpp → Launcher.exe [OK]"

:: ── Stage 2: 編譯 Installer (50 %% → 75 %%) ───────────
echo.
echo [3/4] 正在編譯安裝程式 (EyeSeeMore_Setup.exe) ...
g++ "%INSTALLER_SRC%" "%BUILD_DIR%\app_icon.res" ^
    -o "%BUILD_DIR%\EyeSeeMore_Setup.exe" ^
    -static -static-libgcc -static-libstdc++ ^
    -lole32 -luuid -lshell32
if %errorlevel% neq 0 (
    echo.
    echo [錯誤] Setup 編譯失敗！
    goto :fail
)
call :DrawBar 75 "main_installer.cpp → Setup.exe  [OK]"

:: ── Stage 3: 打包發佈套件 (75 %% → 100 %%) ────────────
echo.
echo [4/7 ~ 7/7] 正在執行發佈打包腳本 (pack_release.py) ...
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

:: [4/7] 初始化輸出目錄 + 複製 Setup.exe
echo.
echo [4/7] 初始化輸出目錄並複製 Setup.exe ...
"!PYTHON_EXE!" "%PACK_SCRIPT%" "!_ROOT!" "%BUILD_DIR%" --task setup
if %errorlevel% neq 0 ( echo. & echo [錯誤] 打包失敗（setup）！ & goto :fail )
call :DrawBar 80 "輸出目錄初始化完成  [OK]"

:: [5/7] App_Code.zip
echo.
echo [5/7] 正在打包 App_Code.zip ...
"!PYTHON_EXE!" "%PACK_SCRIPT%" "!_ROOT!" "%BUILD_DIR%" --task appcode
if %errorlevel% neq 0 ( echo. & echo [錯誤] 打包失敗（App_Code.zip）！ & goto :fail )
call :DrawBar 87 "App_Code.zip  [OK]"

:: [6/7] Runtime.zip
echo.
echo [6/7] 正在打包 Runtime.zip ...
"!PYTHON_EXE!" "%PACK_SCRIPT%" "!_ROOT!" "%BUILD_DIR%" --task runtime
if %errorlevel% neq 0 ( echo. & echo [錯誤] 打包失敗（Runtime.zip）！ & goto :fail )
call :DrawBar 94 "Runtime.zip  [OK]"

:: [7/7] AI_Models.zip（AI 模型，耗時最久）
echo.
echo [7/7] 正在打包 AI_Models.zip（AI 模型，檔案較大，請稍候）...
"!PYTHON_EXE!" "%PACK_SCRIPT%" "!_ROOT!" "%BUILD_DIR%" --task models
if %errorlevel% neq 0 ( echo. & echo [錯誤] 打包失敗（AI_Models.zip）！ & goto :fail )
call :DrawBar 100 "AI_Models.zip 打包完成  [OK]"

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

:: =====================================================
:: :DrawBar  pct  "label"
::   pct   = 0~100 整數
::   label = 步驟說明（可含空白）
::
::   輸出範例：
::   [##########----------]  50%  main_launcher.cpp → Launcher.exe [OK]
::
::   修復說明：
::   1. set "_pct=%%" → 將 % 號存入變數，避免 %% 在非 for 迴圈內
::      被 CMD percent-expansion 階段吃掉，導致 echo 變成 cho
::   2. if !_f! gtr 0 / if !_e! gtr 0 → 防止 CMD for /l 零端點 bug
::      (Windows CMD 對 for /l %%i in (1,1,0) 會多跑一次)
::   3. 改用 !_label! 取代 %~2，避免含特殊字元的標籤被重複展開
:: =====================================================
:DrawBar
setlocal EnableDelayedExpansion
set "_pct=%%"
set "_label=%~2"
set /a "_f=(%~1 * 20) / 100"
set /a "_e=20 - _f"
set "_b="
if !_f! gtr 0 for /l %%i in (1,1,!_f!) do set "_b=!_b!#"
if !_e! gtr 0 for /l %%i in (1,1,!_e!) do set "_b=!_b!-"
set "_p=%~1"
if %~1 lss  10 set "_p=  %~1"
if %~1 geq 10 if %~1 lss 100 set "_p= %~1"
echo   [!_b!] !_p!!_pct!  !_label!
endlocal
exit /b 0
