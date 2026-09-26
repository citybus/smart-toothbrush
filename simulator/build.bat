@echo off
cd /d %~dp0
echo Building simulator...
gcc -o simulator.exe simulator.c -std=c11 -O2 -lm
if %ERRORLEVEL% EQU 0 (
    echo Build successful: simulator\simulator.exe
) else (
    echo Build FAILED!
)
