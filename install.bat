@echo off
cd /d "%~dp0"
title Installing Eris
echo.
echo  Installing Eris - only needed once, takes a few minutes...
echo.
set PY=py -3
where py >nul 2>nul || set PY=python
%PY% --version >nul 2>nul || (
  echo  Python isn't installed. Get it from python.org and tick "Add python.exe to PATH".
  pause & exit /b 1
)
if not exist .venv %PY% -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip -q
.venv\Scripts\python -m pip install -r requirements.txt && .venv\Scripts\python -m pip install --no-deps -r requirements-nodeps.txt
if errorlevel 1 ( echo. & echo  Install failed - copy the error above and send it to Claude. & pause & exit /b 1 )
.venv\Scripts\python -m eris.icon >nul
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\Eris.lnk\"); $s.TargetPath='%CD%\.venv\Scripts\pythonw.exe'; $s.Arguments='-m eris'; $s.WorkingDirectory='%CD%'; $s.IconLocation='%CD%\eris\eris.ico'; $s.Save()"
echo.
echo  Done! From now on just open "Eris" from your Desktop.
start "" "%CD%\.venv\Scripts\pythonw.exe" -m eris
timeout /t 4 >nul
