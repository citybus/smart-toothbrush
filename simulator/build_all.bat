@echo off
echo === Build Per-File Simulator EXEs ===

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set ROOT=%SCRIPT_DIR%..
set DLL_DIR=%ROOT%\dll\all
set SRC=%SCRIPT_DIR%simulator.c
set OUT_DIR=%SCRIPT_DIR%all

if not exist "%DLL_DIR%" (
    echo [ERROR] DLL directory not found: %DLL_DIR%
    echo Please run build_all.bat in jni\ first.
    exit /b 1
)

set COUNT=0
set SUCCESS=0

for /d %%d in ("%DLL_DIR%\*") do (
    set SUBDIR_NAME=%%~nxd
    set DLL_SUBDIR=%%d
    set EXE_SUBDIR=%OUT_DIR%\!SUBDIR_NAME!

    if not exist "!EXE_SUBDIR!" mkdir "!EXE_SUBDIR!"

    for %%f in ("!DLL_SUBDIR!\*.dll") do (
        set DLL_NAME=%%~nf
        set EXE_PATH=!EXE_SUBDIR!\!DLL_NAME!.exe

        echo [BUILD] !SUBDIR_NAME!\!DLL_NAME!.exe ^<- %%f

        gcc -o "!EXE_PATH!" "%SRC%" -lkernel32 -std=gnu11 -O2 2>nul

        if !errorlevel! equ 0 (
            echo   - OK
            set /a SUCCESS+=1
        ) else (
            echo   - FAIL
        )
        set /a COUNT+=1
    )
)

echo.
echo === Done: %SUCCESS%/%COUNT% EXEs built ===
echo Output: %OUT_DIR%

endlocal
