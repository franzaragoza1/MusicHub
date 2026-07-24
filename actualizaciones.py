"""
actualizaciones.py — Comprueba si hay una versión más nueva en GitHub Releases.

No descarga ni instala nada solo: consulta la última Release publicada y, si es
más nueva que la instalada, la interfaz avisa y ofrece descargarla con un clic.
Solo funciona si las Releases del repositorio son PÚBLICAS (si no, GitHub pide
autenticación y el aviso no aparece — el resto del programa sigue igual).
"""

import json
import sys
import urllib.request
import urllib.error

from version import VERSION, GITHUB_REPO


def _a_tupla(v):
    """Convierte '1.10.2' o 'v1.10.2' en (1, 10, 2) para poder comparar."""
    v = (v or "").strip().lstrip("vV")
    partes = []
    for trozo in v.split("."):
        num = ""
        for c in trozo:
            if c.isdigit():
                num += c
            else:
                break
        partes.append(int(num) if num else 0)
    return tuple(partes) if partes else (0,)


def _plataforma():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _asset_para_mi_sistema(assets):
    """Elige el archivo de descarga que corresponde a este sistema operativo."""
    plat = _plataforma()
    for a in assets:
        nombre = (a.get("name") or "").lower()
        if plat == "windows" and "windows" in nombre:
            return a.get("browser_download_url")
        if plat == "macos" and ("macos" in nombre or "mac" in nombre):
            return a.get("browser_download_url")
        if plat == "linux" and "linux" in nombre:
            return a.get("browser_download_url")
    return None


def comprobar():
    """
    Devuelve un dict con el estado de actualización. Nunca lanza: si algo falla
    (sin internet, repo privado, etc.), devuelve ok=False y el programa sigue.
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "MusicHub-Updater",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
    except Exception as e:
        return {"ok": False, "error": str(e), "version_actual": VERSION}

    tag = data.get("tag_name") or ""
    assets = data.get("assets", []) or []
    hay_nueva = _a_tupla(tag) > _a_tupla(VERSION)
    return {
        "ok": True,
        "version_actual": VERSION,
        "version_ultima": tag.lstrip("vV"),
        "hay_nueva": hay_nueva,
        "url_release": data.get("html_url"),
        "url_descarga": _asset_para_mi_sistema(assets),
        "notas": (data.get("body") or "")[:1200],
    }
