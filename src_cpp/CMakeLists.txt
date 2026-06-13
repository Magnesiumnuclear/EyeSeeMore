cmake_minimum_required(VERSION 3.15)
project(EyeSeeMore_Bootstrapper)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

# 啟用 Windows 資源編譯器
enable_language(RC)

# 1. 定義啟動器，並把 resource.rc 一起編譯進去
add_executable(EyeSeeMore_Launcher WIN32
    launcher/main_launcher.cpp
    resources/resource.rc
)

# [新增] 連結 Windows 系統函式庫：ole32 (工具列 COM), uuid, gdi32 (視窗繪圖)
target_link_libraries(EyeSeeMore_Launcher ole32 uuid gdi32)

# 只編譯 C++ 原始碼，不載入會報錯的 resource.rc
add_executable(EyeSeeMore_Setup installer/main_installer.cpp)

# 讓 Setup 連結 Windows 建立捷徑所需的底層函式庫
target_link_libraries(EyeSeeMore_Setup ole32 uuid)

# 2. 自定義標題列 DLL（設計書 §4）
#    提供 ESM_InstallHook / ESM_SetButtonRects / ESM_UninstallHook 給 Python ctypes 呼叫
add_library(EyeSeeMoreWin SHARED
    win_titlebar/titlebar_hook.cpp
)
target_include_directories(EyeSeeMoreWin PRIVATE win_titlebar)
# 編 DLL 時定義 TITLEBARHOOK_EXPORTS，讓 titlebar_hook.h 的 ESM_API 走 dllexport
# 分支（否則預設 dllimport，會出現「definition is marked dllimport」編譯錯誤）。
# 注意：CMake 自動定義的是 EyeSeeMoreWin_EXPORTS，與標頭要的名字不同，必須顯式補上。
target_compile_definitions(EyeSeeMoreWin PRIVATE TITLEBARHOOK_EXPORTS)
target_link_libraries(EyeSeeMoreWin dwmapi user32)
# 保持 C ABI 輸出名稱，不加 lib 前綴
set_target_properties(EyeSeeMoreWin PROPERTIES PREFIX "")
# DLL 輸出到 build/ 根目錄（與 Launcher/Setup 同層）
set_target_properties(EyeSeeMoreWin PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
)