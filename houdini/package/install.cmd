@echo off
rem RAGReel Tutorial panel installer. Double-click, or run from a command prompt.
rem Options are passed through, e.g.:  install.cmd -HoudiniVersion 22.0   /   install.cmd -Uninstall
if not exist "%~dp0install.ps1" (
  echo.
  echo install.ps1 was not found next to install.cmd.
  echo Extract the whole zip first ^(right click the zip, "Extract All"^), then run install.cmd in the extracted folder.
  echo Running install.cmd from inside the zip window does not work.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set RESULT=%ERRORLEVEL%
echo.
if not "%RESULT%"=="0" echo Finished with problems ^(exit code %RESULT%^). Read the [NG] lines above, then see the "troubleshooting" section of install-other-pc.md.
pause
exit /b %RESULT%
