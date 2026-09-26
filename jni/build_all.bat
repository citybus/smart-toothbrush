@echo off
echo === Build Per-File DLLs ===
python "%~dp0build_per_file.py"
if %errorlevel% neq 0 (
    echo Build failed.
    exit /b 1
)
echo === Done ===
