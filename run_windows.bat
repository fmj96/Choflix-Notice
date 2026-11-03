@echo off
setlocal
cd /d "%~dp0"

if not exist "tools\build.py" goto nofiles
if not exist "run.py" goto nofiles
goto haveall

:nofiles
echo.
echo ============================================================
echo  Project files are missing
echo ============================================================
echo.
echo  Folder: %CD%
echo.
echo  "tools\build.py" or "run.py" was not found here.
echo.
echo  This usually means an UPDATE package was extracted into an
echo  empty folder. An update package holds only the files that
echo  CHANGED - it must be copied ON TOP OF a full installation.
echo.
echo  How to fix:
echo    1. Extract the full package  Choflix-Notice-source.zip
echo       (or Choflix-Notice-offline.zip) into this folder.
echo    2. Then copy the update files over it again.
echo    3. Run this file again.
echo.
pause
exit /b 1

:haveall

set "PY="

py -3 -c "import sys" >nul 2>nul
if %errorlevel%==0 set "PY=py -3"
if defined PY goto found

python -c "import sys" >nul 2>nul
if %errorlevel%==0 set "PY=python"
if defined PY goto found

goto nopython

:nopython
echo.
echo ============================================================
echo  Python not found
echo ============================================================
echo.
echo  Choflix Notice needs Python 3.10 or newer to run.
echo.
echo   1. Download:  https://www.python.org/downloads/windows/
echo   2. During setup, CHECK this box:
echo         [v] Add python.exe to PATH
echo   3. Close this window, open a NEW one, run this file again.
echo.
echo  NOTE: If typing "python" opens the Microsoft Store, that is
echo        only a placeholder, not a real install. Use python.org.
echo.
pause
exit /b 1

:found
%PY% "tools\launch.py" %*
set "RC=%errorlevel%"

if not "%RC%"=="0" pause
exit /b %RC%
