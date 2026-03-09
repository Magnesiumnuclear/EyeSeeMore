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

# 2. 安裝程式保留不動
add_executable(EyeSeeMore_Setup 
    installer/main_installer.cpp
)