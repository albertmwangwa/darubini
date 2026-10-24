@echo off
rem Darubini: clone the repo, set up Python, download and profile the datasets.
rem Works from either place:
rem   - next to the repo (e.g. F:\Projects\setup-darubini.cmd -> F:\Projects\darubini)
rem   - inside the repo  (darubini\scripts\setup-darubini.cmd)
rem Safe to run again: finished steps and finished datasets are skipped.
setlocal EnableExtensions
title Darubini setup
set "HERE=%~dp0"
if exist "%HERE%..\.git" (
  for %%I in ("%HERE%..") do set "REPO=%%~fI"
) else (
  set "REPO=%HERE%darubini"
)
for %%I in ("%REPO%\..") do set "ROOT=%%~fI\"
cd /d "%ROOT%"
set "LOG=%ROOT%darubini-setup.log"
set "STATUS=%ROOT%darubini-datasets-status.txt"

echo Darubini setup started %date% %time% > "%LOG%"
echo.
echo  Darubini setup
echo  ==============
echo  Log file: %LOG%
echo.

rem ---- 1. Check prerequisites (offer to install missing ones with winget) ----
rem Pick up tools installed in this session without reopening the window.
set "PATH=%PATH%;%ProgramFiles%\Git\cmd;%LocalAppData%\Programs\Python\Launcher;%LocalAppData%\Microsoft\WindowsApps"

where git >nul 2>&1
if errorlevel 1 call :install Git Git.Git
where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Git is not installed. Get it from https://git-scm.com/download/win then run this again.
  echo [ERROR] git missing >> "%LOG%"
  goto :fail
)

call :findpy
if not defined PY (
  call :install "Python 3.12" Python.Python.3.12
  call :findpy
)
if not defined PY (
  echo [ERROR] Python 3.10+ is not installed. Get it from https://www.python.org/downloads/ and tick "Add to PATH".
  echo [ERROR] python missing >> "%LOG%"
  goto :fail
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo [ERROR] Python 3.10 or newer is required. Found:
  %PY% --version
  goto :fail
)
echo [1/5] Git and Python found.
echo [1/5] prerequisites ok >> "%LOG%"

rem ---- 2. Clone or update the repository ----
if exist "%REPO%\.git" (
  echo [2/5] Repository already here; pulling the latest changes...
  git -C "%REPO%" pull --ff-only >> "%LOG%" 2>&1
) else (
  echo [2/5] Cloning github.com/albertmwangwa/darubini ...
  git clone https://github.com/albertmwangwa/darubini.git "%REPO%" >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo [ERROR] Clone failed. Check your internet connection; details in the log.
    goto :fail
  )
)
cd /d "%REPO%"

rem ---- 3. Python environment ----
if not exist ".venv\Scripts\python.exe" (
  echo [3/5] Creating the Python environment...
  %PY% -m venv .venv >> "%LOG%" 2>&1
  if errorlevel 1 goto :fail
) else (
  echo [3/5] Python environment already exists.
)

echo [4/5] Installing Darubini and its tools (a few minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
".venv\Scripts\python.exe" -m pip install -e ".[dev,notebooks]" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] Install failed; details in the log.
  goto :fail
)

rem ---- 5. Datasets ----
echo [5/5] Downloading datasets into %REPO%\datasets\raw ...
echo       Tanzanian UDOM set first (149 MB), then NLM thick smears (6.4 GB),
echo       NLM thin cells (353 MB) and MP-IDB. Interrupted? Just run this again.
echo.
echo [5/5] downloads started %date% %time% >> "%LOG%"
".venv\Scripts\darubini.exe" download --only udom-tz-thick nih-thick-pf-150 nih-thick-uninfected nih-thin-cells mp-idb
echo [5/5] downloads finished %date% %time% exit=%errorlevel% >> "%LOG%"

".venv\Scripts\darubini.exe" verify > "%STATUS%" 2>&1
".venv\Scripts\darubini.exe" profile >> "%STATUS%" 2>&1
echo.
type "%STATUS%"
echo.
echo  Done. Status saved to %STATUS%
echo  Still to do by hand: nm-aist-tz (needs a Kaggle token), colombia-ins-thick and
echo  nlm-sudan (read their licences first). See datasets\README.md.
echo SETUP COMPLETE %date% %time% >> "%LOG%"
echo.
pause
exit /b 0

:findpy
set "PY="
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if defined PY exit /b 0
where python >nul 2>&1
if errorlevel 1 exit /b 0
python -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=python"
exit /b 0

:install
rem %1 = friendly name, %2 = winget package id. Asks before installing anything.
where winget >nul 2>&1
if errorlevel 1 exit /b 1
echo.
echo  %~1 is not installed.
choice /c YN /m "  Install %~1 now with winget"
if errorlevel 2 exit /b 1
echo [setup] installing %~2 with winget >> "%LOG%"
winget install --id %~2 -e --source winget --accept-package-agreements --accept-source-agreements
if exist "%ProgramFiles%\Git\cmd\git.exe" set "PATH=%PATH%;%ProgramFiles%\Git\cmd"
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do set "PATH=%PATH%;%%~fD;%%~fD\Scripts"
exit /b 0

:fail
echo SETUP FAILED %date% %time% >> "%LOG%"
echo.
echo  Setup stopped. See %LOG%
pause
exit /b 1
