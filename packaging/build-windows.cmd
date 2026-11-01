@echo off
cd /d "%~dp0\.."
python -m venv .build-env
if errorlevel 1 exit /b 1
.build-env\Scripts\python.exe -m pip install pyinstaller==6.22.0
if errorlevel 1 exit /b 1
.build-env\Scripts\python.exe -m PyInstaller --clean --noconfirm --onefile --windowed --name Montaj-Setup --add-data "source;source" --add-data "source-files.json;." --add-data "packaging/models.json;packaging" --add-data "packaging/node.json;packaging" --add-data "packaging/requirements-windows.txt;packaging" packaging\windows_launcher.py
if errorlevel 1 exit /b 1
python -c "from pathlib import Path;import hashlib;p=Path('dist/Montaj-Setup.exe');Path('dist/Montaj-Setup.sha256.txt').write_text(hashlib.sha256(p.read_bytes()).hexdigest()+'  Montaj-Setup.exe\n')"
if errorlevel 1 exit /b 1
