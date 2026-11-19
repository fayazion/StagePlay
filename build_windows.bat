@echo off
setlocal
cd /d "%~dp0"
echo [1/3] Preparation environnement Python...
py -3 -m venv .venv
if errorlevel 1 (echo Python 3 introuvable & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (echo Installation impossible & pause & exit /b 1)
echo [2/3] Recherche VLC...
set "VLCDIR=%ProgramFiles%\VideoLAN\VLC"
if not exist "%VLCDIR%\libvlc.dll" set "VLCDIR=%ProgramFiles(x86)%\VideoLAN\VLC"
if not exist "%VLCDIR%\libvlc.dll" (
 echo VLC non trouve. Installer VLC 64 bits avant de compiler.
 pause
 exit /b 1
)
echo [3/3] Construction dossier portable...
python -m PyInstaller --noconfirm --clean --windowed --onedir --name StagePlayLite --collect-all vlc --add-binary "%VLCDIR%\libvlc.dll;." --add-binary "%VLCDIR%\libvlccore.dll;." --add-data "%VLCDIR%\plugins;plugins" stageplay.py
if errorlevel 1 (echo Echec PyInstaller & pause & exit /b 1)
echo.
echo Compilation terminee: dist\StagePlayLite\StagePlayLite.exe
pause
