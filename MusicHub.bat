@echo off
REM ============================================================
REM  MusicHub - Lanzador
REM  Doble clic aqui para abrir el programa.
REM  La primera vez tarda unos minutos (instala lo necesario).
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "venv\" (
    echo.
    echo === Primera instalacion: esto tarda unos minutos, espera... ===
    echo.
    python -m venv venv
    if errorlevel 1 (
        echo No se encontro Python. Instala Python 3 desde python.org y vuelve a intentarlo.
        pause
        exit /b 1
    )
    call "venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call "venv\Scripts\activate.bat"
    REM Asegura que estan instaladas las dependencias nuevas (p.ej. pywebview)
    REM sin reinstalar todo: pip salta lo que ya esta.
    pip install -r requirements.txt --quiet
)

echo.
echo === Arrancando MusicHub... se abrira en su propia ventana ===
echo === Para cerrar el programa, cierra esta ventana negra ===
echo.
python app.py

pause
