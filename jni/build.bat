@echo off
cd /d %~dp0
if not exist "..\dll" mkdir "..\dll"
echo Building DLL...
gcc -shared -o ..\dll\alg_toothbrushpc.dll alg_toothbrush.c -std=gnu11 "-Wl,--output-def,..\dll\alg_toothbrushpc.def"
if %ERRORLEVEL% EQU 0 (
    echo Build successful: dll\alg_toothbrushpc.dll
) else (
    echo Build FAILED!
)
