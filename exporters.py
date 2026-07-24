"""
exporters.py — Genera los archivos de exportación de listas.

- M3U8  -> para importar manualmente en Rekordbox.
- NML   -> para importar manualmente en Traktor.

No toca ninguna carpeta ni base de datos interna de Rekordbox/Traktor: solo
escribe archivos sueltos en la carpeta de exportación.
"""

import os
import re
from pathlib import Path
from xml.sax.saxutils import quoteattr

EXPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")


def _asegurar_carpeta():
    os.makedirs(EXPORT_DIR, exist_ok=True)


def _nombre_seguro(nombre):
    """Convierte el nombre de la lista en un nombre de archivo válido."""
    limpio = re.sub(r'[<>:"/\\|?*]', "_", nombre).strip()
    return limpio or "lista"


# ----------------------------------------------------------------------------
# M3U8 (Rekordbox)
# ----------------------------------------------------------------------------
def exportar_m3u8(nombre, tracks):
    """
    Genera un archivo .m3u8 (UTF-8). Rekordbox lo importa desde
    Archivo -> Importar -> Lista de reproducción.
    """
    _asegurar_carpeta()
    ruta_salida = os.path.join(EXPORT_DIR, _nombre_seguro(nombre) + ".m3u8")

    lineas = ["#EXTM3U"]
    for t in tracks:
        dur = int(round(t.get("duracion") or 0))
        artista = t.get("artista") or ""
        titulo = t.get("titulo") or ""
        lineas.append(f"#EXTINF:{dur},{artista} - {titulo}")
        # Ruta absoluta de Windows tal cual (Rekordbox la resuelve en local).
        lineas.append(t["ruta"])

    with open(ruta_salida, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lineas) + "\n")

    return ruta_salida


# ----------------------------------------------------------------------------
# NML (Traktor)
# ----------------------------------------------------------------------------
def _ruta_traktor(ruta):
    """
    Convierte una ruta de Windows al formato de LOCATION de Traktor.

    Ejemplo:
      D:\\Musica\\Techno\\tema.mp3
      -> VOLUME="D:"  DIR="/:Musica/:Techno/:"  FILE="tema.mp3"
    """
    p = Path(ruta)
    volume = p.drive  # "D:"
    file = p.name
    # Partes de la carpeta entre la unidad y el archivo.
    partes = p.parts[1:-1] if len(p.parts) > 2 else []
    dir_traktor = "/:" + "".join(part + "/:" for part in partes)
    if dir_traktor == "/:":
        dir_traktor = "/:"
    return volume, dir_traktor, file


def exportar_nml(nombre, tracks):
    """
    Genera un archivo .nml (XML de Traktor) con una COLLECTION mínima y una
    PLAYLIST. Sin cues ni beatgrid. Traktor lo importa con clic derecho sobre
    Playlists -> Import Playlist.
    """
    _asegurar_carpeta()
    ruta_salida = os.path.join(EXPORT_DIR, _nombre_seguro(nombre) + ".nml")

    entries = []
    keys = []
    for t in tracks:
        volume, dir_traktor, file = _ruta_traktor(t["ruta"])
        artista = t.get("artista") or ""
        titulo = t.get("titulo") or ""
        genero = t.get("genero") or ""
        bpm = t.get("bpm")
        dur = t.get("duracion") or 0
        tonalidad = t.get("tonalidad") or ""

        info_extra = f'GENRE={quoteattr(genero)} PLAYTIME="{int(round(dur))}"'
        if tonalidad:
            info_extra += f' KEY_LYRICS={quoteattr(tonalidad)}'
        tempo_xml = f'      <TEMPO BPM="{bpm:.2f}" BPM_QUALITY="100"/>\n' if bpm else ""

        entry = (
            f'    <ENTRY MODIFIED_DATE="2024/1/1" ARTIST={quoteattr(artista)} '
            f'TITLE={quoteattr(titulo)}>\n'
            f'      <LOCATION DIR={quoteattr(dir_traktor)} FILE={quoteattr(file)} '
            f'VOLUME={quoteattr(volume)} VOLUMEID={quoteattr(volume)}/>\n'
            f'      <INFO {info_extra}/>\n'
            f'{tempo_xml}'
            f'    </ENTRY>'
        )
        entries.append(entry)

        # La PRIMARYKEY apunta al archivo por su ruta Traktor completa.
        clave = f"{volume}{dir_traktor}{file}"
        keys.append(
            f'        <ENTRY><PRIMARYKEY TYPE="TRACK" KEY={quoteattr(clave)}/></ENTRY>'
        )

    nml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<NML VERSION="19">\n'
        '  <HEAD COMPANY="www.native-instruments.com" PROGRAM="Traktor"/>\n'
        f'  <COLLECTION ENTRIES="{len(entries)}">\n'
        + "\n".join(entries) + "\n"
        '  </COLLECTION>\n'
        '  <PLAYLISTS>\n'
        '    <NODE TYPE="FOLDER" NAME="$ROOT">\n'
        '      <SUBNODES COUNT="1">\n'
        f'        <NODE TYPE="PLAYLIST" NAME={quoteattr(nombre)}>\n'
        f'          <PLAYLIST ENTRIES="{len(keys)}" TYPE="LIST" UUID="musichub">\n'
        + "\n".join(keys) + "\n"
        '          </PLAYLIST>\n'
        '        </NODE>\n'
        '      </SUBNODES>\n'
        '    </NODE>\n'
        '  </PLAYLISTS>\n'
        '</NML>\n'
    )

    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write(nml)

    return ruta_salida
