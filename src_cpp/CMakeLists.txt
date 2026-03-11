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