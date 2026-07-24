# -*- mode: python ; coding: utf-8 -*-
"""
Spec de PyInstaller para MusicHub (Windows y macOS).

Genera una app en carpeta (onedir): fiable con librosa/numba. En macOS produce
además MusicHub.app. Se usa igual en local y en GitHub Actions:

    pyinstaller --noconfirm MusicHub.spec
"""
import os
import sys
from PyInstaller.utils.hooks import collect_all

# --- Datos base: las plantillas y los estáticos de la web ---
datas = [("templates", "templates"), ("static", "static")]
binaries = []
hiddenimports = []

# Paquetes que PyInstaller no recoge bien solo: los coleccionamos enteros.
for paquete in [
    "librosa", "numba", "llvmlite", "sklearn", "soundfile", "audioread",
    "lazy_loader", "pooch", "soxr", "msgpack", "decorator", "joblib",
    "threadpoolctl", "webview",
]:
    try:
        d, b, h = collect_all(paquete)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec] Aviso: no se pudo coleccionar {paquete}: {e}")

# Clave gratis embebida (si el CI la generó desde un secreto). Se incluye en el
# ejecutable para que la IA funcione sin configurar nada. No está en el repo.
if os.path.exists("_clave_embebida.py"):
    hiddenimports.append("_clave_embebida")

# Con console=True se ve la salida (útil para depurar). Por defecto sin consola
# (para que no aparezca ninguna ventana negra). Local: MUSICHUB_CONSOLE=1.
CONSOLA = bool(os.environ.get("MUSICHUB_CONSOLE"))

# Icono de la app: .ico en Windows (exe, barra de tareas), .icns en macOS (Dock).
ICONO_WIN = "logos/icon.ico"
ICONO_MAC = "logos/icon.icns"
ICONO_EXE = ICONO_WIN if sys.platform == "win32" else (ICONO_MAC if sys.platform == "darwin" else None)

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MusicHub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLA,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICONO_EXE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MusicHub",
)

# En macOS, empaquetar como MusicHub.app
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="MusicHub.app",
        icon=ICONO_MAC,
        bundle_identifier="com.musichub.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleName": "MusicHub",
            "CFBundleDisplayName": "MusicHub",
            "LSMinimumSystemVersion": "10.15",
        },
    )
