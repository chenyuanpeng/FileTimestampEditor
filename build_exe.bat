@echo off
setlocal
py -m pip install --upgrade pyinstaller -r requirements.txt
py -m PyInstaller --noconfirm --clean --windowed --collect-all tkinterdnd2 --name FileTimestampEditor timestamp_editor.py
echo.
echo Done. Your executable is: dist\FileTimestampEditor\FileTimestampEditor.exe
pause
