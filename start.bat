@echo off
rem Launcher for Tyre Finder (Windows). Uses uv if available, otherwise a local venv with pip.
cd /d "%~dp0"
where uv >nul 2>nul
if %errorlevel%==0 (
    uv sync --quiet || goto :error
    uv run tyre-finder
    goto :eof
)
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3.12 -m venv .venv 2>nul || python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -e . || goto :error
)
start "" ".venv\Scripts\pythonw.exe" -m tyre_finder.app
goto :eof
:error
echo Failed to start Tyre Finder.
pause
