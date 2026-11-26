@echo off
rem RAGReel Tutorial panel uninstaller. Double-click, or run from a command prompt.
rem Removes the Houdini package registration and %LOCALAPPDATA%\RAGReelTutorial. Your settings file and the
rem generated tutorials (Documents\RAGReelTutorial) are kept.
rem After installing, the same thing is also in  Settings > Apps > Installed apps > RAGReel Tutorial.
if not exist "%~dp0install.ps1" (
  echo.
  echo install.ps1 was not found next to uninstall.cmd.
  echo Extract the whole zip first ^(right click the zip, "Extract All"^), then run uninstall.cmd in the extracted folder.
  echo Or remove it from  Settings ^> Apps ^> Installed apps ^> RAGReel Tutorial.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Uninstall %*
set RESULT=%ERRORLEVEL%
echo.
pause
exit /b %RESULT%
