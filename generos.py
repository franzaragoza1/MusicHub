"""
generos.py — Normalización y comparación de géneros.

El objetivo es evitar el caos típico de etiquetas que vienen de mil sitios:
  - multi-género:      "House / Electronic / Techno" -> "House"
  - separadores varios: "House, Deep House" / "Garage; House" / "Indie Dance - Nu Disco"
  - basura:            "hiphopde.com", "https://djsoundtop.com"  -> (vacío)
  - fechas:            "House 02/22", "House 2021"  -> "House"
  - espacios/comillas sobrantes.

`normalizar()` se aplica al escanear (y opcionalmente al editar) para que no
entren duplicados nuevos. `clave()` sirve para agrupar variantes que son "el
mismo" género (ignora mayúsculas y acentos).
"""

import re
import unicodedata

# Separadores que indican varios géneros o jerarquía: nos quedamos con el primero.
# Ojo: el guion solo separa si va rodeado de espacios (" - "), para no romper
# géneros con guion como "Drum-n-Bass" o "Hip-Hop".
_SEP = re.compile(r"\s*[/;,]\s*|\s+[-–—]\s+")
_URL = re.compile(r"https?://|www\.", re.I)
_FECHA = re.compile(r"\s*\d{1,2}[/.\-]\d{2,4}\s*$|\s+\d{4}\s*$")
# Dominio suelto tipo "sharingdb.top", "hiphopde.com": palabra(s).tld
_DOMINIO = re.compile(r"^[\w-]+(?:\.[\w-]+)+$")

# Placeholders y etiquetas que no son un género de verdad.
_BASURA = {
    "other", "others", "otro", "otros", "otros generos", "otros géneros",
    "unknown", "desconocido", "varios", "various", "misc", "miscellaneous",
    "none", "sin genero", "sin género", "n/a", "na", "genre", "genero", "género",
    "untagged", "sin etiquetar",
}


def _es_basura(g):
    gl = g.lower().strip()
    return bool(gl in _BASURA or _DOMINIO.match(gl))


def normalizar(g):
    """Devuelve el género limpio, o '' si no es un género válido."""
    if not g:
        return ""
    g = str(g).replace("\x00", " ").strip()
    if not g or _URL.search(g):
        return ""
    # Descriptores de estilo entre paréntesis: "Techno (Peak Time / Driving)" -> "Techno".
    g = re.sub(r"\s*\([^)]*\)", "", g).strip()
    g = _FECHA.sub("", g).strip()         # "House 02/22" -> "House"  (antes de separar)
    g = _SEP.split(g)[0].strip()          # "House / Techno" -> "House"
    g = _FECHA.sub("", g).strip()         # por si quedó una fecha en el primer género
    g = re.sub(r"\s+", " ", g).strip(" -–—/;,.\t")
    # Descartar restos sin sentido (vacío, solo números, una letra) y placeholders.
    if len(g) < 2 or g.isdigit() or _es_basura(g):
        return ""
    return g


def clave(g):
    """Clave de agrupación de variantes: normalizada, en minúsculas y sin acentos."""
    g = normalizar(g).lower()
    g = "".join(c for c in unicodedata.normalize("NFKD", g) if not unicodedata.combining(c))
    return g.strip()
