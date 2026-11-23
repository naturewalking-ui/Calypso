@echo off
setlocal enabledelayedexpansion

REM Always run from the directory containing this script
cd /d "%~dp0"

REM 1. Install global system dependencies via winget
echo Installing system packages...
winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
winget install --id Kitware.CMake -e --accept-package-agreements --accept-source-agreements
winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
winget install --id eSpeak-NG.eSpeak-NG -e --accept-package-agreements --accept-source-agreements
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --accept-package-agreements --accept-source-agreements --override "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"

REM Refresh PATH for newly installed tools in the current session
set "PATH=%PATH%;%ProgramFiles%\Git\cmd;%ProgramFiles%\CMake\bin;%ProgramFiles%\eSpeak NG"

REM 2. Initialize virtual environment specifically with Python 3.12 (64-bit)
if not exist "venv\Scripts\python.exe" (
    echo Creating Python 3.12 virtual environment...
    py -3.12 -m venv venv
    if errorlevel 1 (
        echo [ERROR] Python 3.12 not found. Please install 64-bit Python 3.12 and retry.
        goto :error
    )
)

REM 3. Upgrade pip and build tools
echo Upgrading pip...
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :error

REM 4. Install PyTorch (CUDA 13.0) - verified matching trio
echo Verifying / Installing PyTorch (CUDA 13.0)...
venv\Scripts\python.exe -m pip install torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cu130
if errorlevel 1 goto :error


REM 5. Sync project dependencies
if exist "requirements.txt" (
    echo Syncing dependencies from requirements.txt...
    venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 goto :error
) else (
    echo Warning: requirements.txt not found. Skipping dependency sync.
)

REM 6. Initialize local NLTK data directory (owner-only permissions for NLTK >= 3.10)
echo Downloading NLTK VADER lexicon into .\nltk_data...
if not exist "nltk_data" mkdir nltk_data
icacls "nltk_data" /inheritance:r /grant:r "%USERNAME%:(OI)(CI)F" >nul

venv\Scripts\python.exe -c "import nltk; nltk.download('vader_lexicon', download_dir='nltk_data')"
if errorlevel 1 goto :error

icacls "nltk_data" /inheritance:r /grant:r "%USERNAME%:(OI)(CI)F" /T >nul

echo.
echo ========================================
echo   Calypso installation complete!
echo   You can now run launch.bat to start.
echo ========================================
pause
exit /b 0

:error
echo.
echo [ERROR] Installation failed at the step above.
pause
exit /b 1
