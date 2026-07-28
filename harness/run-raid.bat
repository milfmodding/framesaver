@echo off
REM One command: server up, client up, both down when the game closes.
REM Any arguments are passed through, e.g.  run-raid.bat -DryRun
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-raid.ps1" %*
