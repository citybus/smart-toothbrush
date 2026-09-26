@echo off
echo === Run All Per-File Simulators ===

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set ROOT=%SCRIPT_DIR%..
set EXE_DIR=%SCRIPT_DIR%all
set INPUT_DIR=%ROOT%\input
set OUTPUT_DIR=%ROOT%\output

if not exist "%EXE_DIR%" (
    echo [ERROR] EXE directory not found: %EXE_DIR%
    echo Please run build_all.bat first.
    exit /b 1
)

set TOTAL=0

for /d %%d in ("%EXE_DIR%\*") do (
    set SUBDIR_NAME=%%~nxd
    set EXE_SUBDIR=%%d
    set INPUT_SUBDIR=%INPUT_DIR%\!SUBDIR_NAME!
    set OUTPUT_SUBDIR=%OUTPUT_DIR%\!SUBDIR_NAME!

    if not exist "!OUTPUT_SUBDIR!" mkdir "!OUTPUT_SUBDIR!"

    echo.
    echo [DIR] !SUBDIR_NAME!

    for %%f in ("!EXE_SUBDIR!\*.exe") do (
        set EXE_NAME=%%~nf
        set INPUT_FILE=!INPUT_SUBDIR!\!EXE_NAME!.txt

        if exist "!INPUT_FILE!" (
            echo   [RUN] !EXE_NAME!.exe
            "%%f" "!INPUT_SUBDIR!" "!OUTPUT_SUBDIR!" "!INPUT_FILE!"
            set /a TOTAL+=1
        ) else (
            echo   [SKIP] !EXE_NAME! ^(no matching input file^)
        )
    )
)

echo.
echo === Done: processed %TOTAL% files ===

endlocal
