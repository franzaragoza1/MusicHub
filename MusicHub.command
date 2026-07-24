#!/bin/bash
# ============================================================
#  MusicHub - Lanzador para macOS y Linux
#  Doble clic aqui para abrir el programa.
#  La primera vez tarda unos minutos (instala lo necesario).
#
#  NOTA para macOS: la primera vez, si Finder no deja abrirlo,
#  haz clic derecho sobre el archivo -> Abrir. Y si hace falta,
#  dale permiso de ejecucion una vez con:  chmod +x MusicHub.command
# ============================================================
cd "$(dirname "$0")"

# Elegir el interprete de Python disponible.
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "No se encontro Python 3. Instalalo desde https://www.python.org/downloads/"
    read -n 1 -s -r -p "Pulsa una tecla para salir..."
    exit 1
fi

if [ ! -d "venv" ]; then
    echo ""
    echo "=== Primera instalacion: esto tarda unos minutos, espera... ==="
    echo ""
    "$PY" -m venv venv || { echo "No se pudo crear el entorno."; read -n 1 -s -r; exit 1; }
    source venv/bin/activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt
else
    source venv/bin/activate
    # Asegura dependencias nuevas (p.ej. pywebview) sin reinstalar todo.
    pip install -r requirements.txt --quiet
fi

echo ""
echo "=== Arrancando MusicHub... se abrira en su propia ventana ==="
echo "=== Para cerrar el programa, cierra esta ventana de Terminal ==="
echo ""
python app.py
