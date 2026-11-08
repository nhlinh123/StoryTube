@echo off
rem StoryTube — mở giao diện web tại http://127.0.0.1:8790
cd /d "%~dp0"
set TMP=%~dp0..\.tmp
set TEMP=%~dp0..\.tmp
python -m storytube serve --open
