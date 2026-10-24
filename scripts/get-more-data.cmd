@echo off
rem Fetch the extra Darubini datasets: NM-AIST Tanzania (Kaggle), Colombia INS (Zenodo)
rem and NLM Sudan (49 GB). Run after setup-darubini.cmd. Safe to rerun.
rem --accept-licences is passed because the owner accepted these terms on 24 Oct 2026:
rem   NLM Sudan: credit "Source: U.S. National Library of Medicine", cite Yu et al. 2023.
rem   Colombia INS: no licence stated; research use with attribution only.
setlocal EnableExtensions
title Darubini extra datasets
set "HERE=%~dp0"
if exist "%HERE%..\.git" (
  for %%I in ("%HERE%..") do set "REPO=%%~fI"
) else (
  set "REPO=%HERE%darubini"
)
for %%I in ("%REPO%\..") do set "ROOT=%%~fI\"
set "LOG=%ROOT%darubini-more-data.log"
set "STATUS=%ROOT%darubini-datasets-status.txt"

if not exist "%REPO%\.venv\Scripts\darubini.exe" (
  echo Run setup-darubini.cmd first.
  pause
  exit /b 1
)
cd /d "%REPO%"
rem The venv's tools (including the Kaggle CLI) must be on PATH for the downloader.
set "PATH=%REPO%\.venv\Scripts;%PATH%"
echo Extra datasets started %date% %time% > "%LOG%"

git pull --ff-only >> "%LOG%" 2>&1
python -m pip install -e . kaggle >> "%LOG%" 2>&1

echo.
echo [1/3] NM-AIST Tanzania via Kaggle
if exist "%USERPROFILE%\.kaggle\kaggle.json" (
  darubini download --only nm-aist-tz
) else (
  echo   No Kaggle token found at %USERPROFILE%\.kaggle\kaggle.json
  echo   Create one at kaggle.com ^> Settings ^> API ^> Create New Token, save it there, and rerun.
  echo [1/3] skipped: no kaggle.json >> "%LOG%"
)

echo.
echo [2/3] Colombia INS thick smears (about 8 GB)
darubini download --only colombia-ins-thick --accept-licences

echo.
echo [3/3] NLM Sudan (49 GB; about 100 GB free needed while it unpacks)
darubini download --only nlm-sudan --accept-licences

darubini verify > "%STATUS%" 2>&1
darubini profile >> "%STATUS%" 2>&1
echo.
type "%STATUS%"
echo Extra datasets finished %date% %time% >> "%LOG%"
echo.
echo  Done. Status saved to %STATUS%
pause
