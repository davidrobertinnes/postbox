@echo off
setlocal EnableDelayedExpansion
title Dogbox Mailman - Windows Installer

cd /d "%~dp0"

echo.
echo  ============================================================
echo   Dogbox Mailman - AI Email Client - Windows Installer
echo  ============================================================
echo.

REM ── Step 1: Find Python ──────────────────────────────────────────────────────

set PYTHON_EXE=

if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe& goto :verify_python)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe& goto :verify_python)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe& goto :verify_python)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe& goto :verify_python)
if exist "%ProgramFiles%\Python313\python.exe" (
    set PYTHON_EXE=%ProgramFiles%\Python313\python.exe& goto :verify_python)
if exist "%ProgramFiles%\Python312\python.exe" (
    set PYTHON_EXE=%ProgramFiles%\Python312\python.exe& goto :verify_python)
if exist "%ProgramFiles%\Python311\python.exe" (
    set PYTHON_EXE=%ProgramFiles%\Python311\python.exe& goto :verify_python)
if exist "%ProgramFiles%\Python310\python.exe" (
    set PYTHON_EXE=%ProgramFiles%\Python310\python.exe& goto :verify_python)
if exist "C:\Python313\python.exe" (
    set PYTHON_EXE=C:\Python313\python.exe& goto :verify_python)
if exist "C:\Python312\python.exe" (
    set PYTHON_EXE=C:\Python312\python.exe& goto :verify_python)

where py >nul 2>&1
if %errorlevel% == 0 (
    set PYTHON_EXE=py& goto :verify_python)

for /f "delims=" %%i in ('where python 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
        set PYTHON_EXE=%%i& goto :verify_python)
)

goto :download_python

:verify_python
"%PYTHON_EXE%" -c "import sys; sys.exit(0)" >nul 2>&1
if %errorlevel% neq 0 (
    set PYTHON_EXE=
    goto :download_python
)
goto :found_python

:download_python
echo  [ INFO ] Python not found. Downloading and installing Python automatically...
echo.

set PY_URL=https://www.python.org/ftp/python/3.13.3/python-3.13.3-amd64.exe
set PY_INSTALLER=%TEMP%\mailman_python_setup.exe

echo  Downloading Python 3.13...
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_INSTALLER%' -UseBasicParsing"

if not exist "%PY_INSTALLER%" (
    echo.
    echo  [ERROR ] Download failed. Check your internet connection and try again.
    echo           Or install Python manually from: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo  Installing Python silently (this may take a minute)...
"%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1

del /f /q "%PY_INSTALLER%" >nul 2>&1

if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe
    goto :verify_python
)
where py >nul 2>&1
if %errorlevel% == 0 (
    set PYTHON_EXE=py
    goto :verify_python
)

echo.
echo  [ INFO ] Python was installed. Please close this window and
echo           double-click wininstall.bat again to complete setup.
echo.
pause
exit /b 0

:found_python
for /f "tokens=*" %%v in ('"%PYTHON_EXE%" --version 2^>^&1') do set PY_VER=%%v
echo  [  OK  ] Found %PY_VER%
echo.

REM ── Step 2: Install required packages ────────────────────────────────────────

echo  Checking required packages...
echo.

set MISSING=0

"%PYTHON_EXE%" -c "import flask" >nul 2>&1
if %errorlevel% neq 0 set MISSING=1

"%PYTHON_EXE%" -c "import imapclient" >nul 2>&1
if %errorlevel% neq 0 set MISSING=1

"%PYTHON_EXE%" -c "import keyring" >nul 2>&1
if %errorlevel% neq 0 set MISSING=1

if %MISSING% == 0 (
    echo  [  OK  ] Required packages already installed.
    goto :shortcut
)

echo  [ WARN ] Some required packages are missing.
echo.
set /p INSTALLPKG="  Install them now? [Y/n] "
if /i "%INSTALLPKG%"=="n" (
    echo.
    echo  [ WARN ] Skipping. Dogbox Mailman will not run until packages are installed.
    echo           Run:  pip install flask imapclient keyring google-auth-oauthlib msal anthropic bleach beautifulsoup4
    goto :shortcut
)

echo.
echo  Installing packages (this may take a minute)...
"%PYTHON_EXE%" -m pip install --upgrade pip -q
"%PYTHON_EXE%" -m pip install flask imapclient keyring google-auth-oauthlib msal anthropic bleach beautifulsoup4 google-auth -q

if %errorlevel% neq 0 (
    echo.
    echo  [ERROR ] pip install failed. Check your internet connection and try again.
    pause
    exit /b 1
)
echo  [  OK  ] Packages installed.

REM ── Step 3: Create desktop shortcut ──────────────────────────────────────────

:shortcut
echo.
echo  Creating desktop shortcut...

set MAIL_PY=%~dp0mail.py

powershell -NoProfile -Command "$desktop = [Environment]::GetFolderPath('Desktop'); $ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut($desktop + '\Dogbox Mailman.lnk'); $s.TargetPath = '%PYTHON_EXE%'; $s.Arguments = '\"%MAIL_PY%\"'; $s.WorkingDirectory = '%~dp0'; $s.WindowStyle = 1; $s.Description = 'Dogbox Mailman - AI Email Client'; $s.Save()"

if %errorlevel% == 0 (
    echo  [  OK  ] Desktop shortcut created: "Dogbox Mailman"
) else (
    echo  [ WARN ] Could not create desktop shortcut automatically.
    echo           Right-click mail.py and choose "Open with Python" to run manually.
)

REM ── Done ──────────────────────────────────────────────────────────────────────

echo.
echo  ============================================================
echo   Installation complete!
echo.
echo   Double-click the "Dogbox Mailman" shortcut on your desktop
echo   to launch. It opens in your browser automatically.
echo.
echo   Or run from a terminal:
echo     python mail.py
echo  ============================================================
echo.

set /p LAUNCH="  Launch Dogbox Mailman now? [Y/n] "
if /i not "%LAUNCH%"=="n" (
    start "" "%PYTHON_EXE%" "%MAIL_PY%"
)

echo.
pause
exit /b 0
