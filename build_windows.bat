@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3.12") else (set "PY=python")
%PY% -m pip install --upgrade pip
if errorlevel 1 goto bad
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto bad
%PY% -m unittest discover -s tests -v
if errorlevel 1 goto bad
set "VLC=C:\Program Files\VideoLAN\VLC"
if not exist "%VLC%\libvlc.dll" (
 echo VLC 64 bits non trouve dans %%ProgramFiles%%. Installe VLC 64 bits.
 goto bad
)
%PY% -m PyInstaller --noconfirm --clean --windowed --onedir --name StagePlayV2 --collect-all vlc --collect-all pymupdf --add-binary "%VLC%\libvlc.dll;." --add-binary "%VLC%\libvlccore.dll;." --add-data "%VLC%\plugins;plugins" stageplay.py
if errorlevel 1 goto bad
echo.
echo Programme portable cree: dist\StagePlayV2\StagePlayV2.exe
goto end
:bad
echo Une erreur a interrompu la compilation.
:end
pause
