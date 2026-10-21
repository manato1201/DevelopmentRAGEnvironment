@echo off
rem RAGReel Tutorial panel installer. Double-click, or run from a command prompt.
rem Options are passed through, e.g.:  install.cmd -HoudiniVersion 22.0   /   install.cmd -Uninstall
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
