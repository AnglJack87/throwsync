@echo off
REM Read version
set "VERSION=?.?.?"
if exist "%~dp0VERSION" (
    set /p VERSION=<"%~dp0VERSION"
)

title ThrowSync v%VERSION%

echo ========================================
echo   THROWSYNC v%VERSION%
echo   WLED + Autodarts + Caller + ESP Flasher
echo ========================================
echo.

REM --- Python pruefen ---
REM Windows hat einen python.exe Stub der zum Microsoft Store leitet.
REM Deshalb pruefen wir ob Python WIRKLICH Code ausfuehren kann:

python -c "import sys; sys.exit(0)" >nul 2>&1
if %ERRORLEVEL% neq 0 goto :no_python

echo Python gefunden:
python --version
echo.
goto :python_ok

:no_python
echo ========================================
echo   PYTHON IST NICHT INSTALLIERT!
echo ========================================
echo.
echo   So installierst du Python:
echo.
echo   1. Oeffne: https://www.python.org/downloads/
echo   2. Klicke "Download Python 3.x"
echo   3. Installer starten
echo   4. WICHTIG: Haken setzen bei:
echo.
echo      [x] Add Python to PATH
echo.
echo      DAS WIRD OFT VERGESSEN!
echo.
echo   5. "Install Now" klicken
echo   6. Danach dieses Fenster schliessen
echo      und start.bat NEU starten
echo.
echo ----------------------------------------
echo.
echo   Falls Python installiert ist aber
echo   nicht erkannt wird:
echo.
echo   Windows Einstellungen oeffnen:
echo   Apps ^> Erweiterte App-Einstellungen
echo   ^> App-Ausfuehrungsaliase
echo   ^> "python.exe" auf AUS stellen
echo.
echo ========================================
echo.
start https://www.python.org/downloads/
pause
exit /b 1

:python_ok

REM --- Abhaengigkeiten pruefen ---

python -c "import fastapi" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Installiere Abhaengigkeiten...
    echo.
    python -m pip install -r "%~dp0requirements.txt"
    if %ERRORLEVEL% neq 0 (
        echo.
        echo Erster Versuch fehlgeschlagen, versuche Alternative...
        python -m pip install fastapi uvicorn[standard] aiohttp python-multipart pyserial esptool
        if %ERRORLEVEL% neq 0 (
            echo.
            echo ========================================
            echo   INSTALLATION FEHLGESCHLAGEN!
            echo ========================================
            echo.
            echo   Versuche manuell:
            echo.
            echo   python -m pip install --upgrade pip
            echo   python -m pip install fastapi uvicorn aiohttp
            echo.
            pause
            exit /b 1
        )
    )
    echo.
    echo Abhaengigkeiten erfolgreich installiert!
    echo.
)

REM --- Server starten ---

echo Starte ThrowSync...
echo.
echo   Lokal:    http://localhost:8420
echo   Netzwerk: http://DEINE-IP:8420
echo.
echo   Druecke Strg+C zum Beenden
echo.

cd /d "%~dp0"
python run.py

echo.
echo Server beendet.
pause
