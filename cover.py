"""
cover.py — Extrae la portada (carátula) incrustada en un archivo de música.

Devuelve (bytes_imagen, tipo_mime) o (None, None) si no hay portada.
Soporta las carátulas incrustadas en MP3/WAV/AIFF (ID3 APIC), FLAC (pictures),
M4A (covr) y OGG (metadata_block_picture).
"""

import base64
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis


def extraer_portada(ruta):
    ext = Path(ruta).suffix.lower().lstrip(".")
    try:
        if ext in ("mp3", "wav", "aiff", "aif"):
            audio = mutagen.File(ruta)
            if audio is not None and audio.tags is not None:
                for clave in audio.tags.keys():
                    if clave.startswith("APIC"):
                        apic = audio.tags[clave]
                        return bytes(apic.data), (apic.mime or "image/jpeg")

        elif ext == "flac":
            f = FLAC(ruta)
            if f.pictures:
                p = f.pictures[0]
                return bytes(p.data), (p.mime or "image/jpeg")

        elif ext == "m4a":
            m = MP4(ruta)
            covr = m.tags.get("covr") if m.tags else None
            if covr:
                c = covr[0]
                mime = "image/png" if c.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
                return bytes(c), mime

        elif ext == "ogg":
            o = OggVorbis(ruta)
            b64 = o.get("metadata_block_picture")
            if b64:
                pic = Picture(base64.b64decode(b64[0]))
                return bytes(pic.data), (pic.mime or "image/jpeg")

    except Exception:
        pass
    return None, None
