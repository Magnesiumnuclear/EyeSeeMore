cmake_minimum_required(VERSION 3.15)
project(EyeSeeMore_Bootstrapper)

# 設定使用 C++ 17 標準
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

# 1. 定義啟動器 (Launcher) 的編譯規則
# 加入 WIN32 關鍵字，徹底消除啟動時的 CMD 黑底視窗
add_executable(EyeSeeMore_Launcher WIN32
    launcher/main_launcher.cpp
)

# 2. 定義安裝程式 (Setup) 的編譯規則
add_executable(EyeSeeMore_Setup 
    installer/main_installer.cpp
)