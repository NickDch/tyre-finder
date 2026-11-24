@echo off
rem Builds dist\TyreFinder\TyreFinder.exe with PyInstaller (Windows).
rem Usage: build_exe.bat          -> folder build (fast start, recommended)
rem        build_exe.bat onefile  -> single TyreFinder.exe (slower start)
cd /d "%~dp0"
set MODE=--onedir
if /i "%~1"=="onefile" set MODE=--onefile
where uv >nul 2>nul
if %errorlevel%==0 (
    uv sync --quiet || goto :error
    uv run --with pyinstaller pyinstaller --noconfirm --clean --windowed %MODE% --name TyreFinder --paths src --collect-submodules tyre_finder packaging\launcher.py || goto :error
) else (
    if not exist ".venv\Scripts\python.exe" (
        py -3.12 -m venv .venv 2>nul || python -m venv .venv || goto :error
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -e . pyinstaller || goto :error
    ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed %MODE% --name TyreFinder --paths src --collect-submodules tyre_finder packaging\launcher.py || goto :error
)
echo.
echo Done. Output is in the "dist" folder.
pause
goto :eof
:error
echo Build failed.
pause
