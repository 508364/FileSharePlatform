@echo off

REM 检测是否为64位系统
reg Query "HKLM\Hardware\Description\System\CentralProcessor\0" | find /i "x86" > NUL && set OS=32BIT || set OS=64BIT

if "%OS%"=="32BIT" (
    echo 错误: 此程序仅支持64位Windows系统
    goto exit
)

if exist "%PYTHON_PATH%" (
    echo 使用Python路径: %PYTHON_PATH%
    echo 安装所需的Python包...
    call start.bat
    cls
    "%PYTHON_PATH%"  server.py
) else (
    echo 没有找到Python: %PYTHON_PATH%
    echo 启动python3.12.9静默安装程序...
    start /wait "" "%~dp0start\python-3.12.9-amd64.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
    call start.bat
    echo 安装完成后请重新运行此脚本
)

: exit
echo 脚本退出...
pause > nul