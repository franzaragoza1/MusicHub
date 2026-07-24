"""
tags.py — Escritura de etiquetas en los archivos de música.

SOLO escribe el campo de género (y opcionalmente el BPM). Nunca toca otros
campos ni ningún otro archivo. Si un formato no admite escritura fiable o el
archivo está bloqueado, se lanza una excepción y quien llama decide (en la
práctica: se guarda solo en la base de datos y se avisa al usuario).
"""

from pathlib import Path

import mutagen
from mutagen.id3 import ID3, TCON, TBPM, ID3NoHeaderError
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4
from mutagen.easyid3 import EasyID3
from mutagen.wave import WAVE
from mutagen.aiff import AIFF


def _es_id3(formato):
    return formato in ("mp3", "wav", "aiff", "aif")


def escribir_genero(ruta, genero):
    """
    Escribe el género en la etiqueta del archivo. Lanza excepción si falla.
    """
    ext = Path(ruta).suffix.lower().lstrip(".")
    genero = genero or ""

    if ext == "mp3":
        try:
            audio = EasyID3(ruta)
        except ID3NoHeaderError:
            audio = mutagen.File(ruta, easy=True)
            audio.add_tags()
        audio["genre"] = genero
        audio.save()

    elif ext in ("flac", "ogg"):
        audio = FLAC(ruta) if ext == "flac" else OggVorbis(ruta)
        audio["genre"] = genero
        audio.save()

    elif ext == "m4a":
        audio = MP4(ruta)
        audio["\xa9gen"] = [genero]
        audio.save()

    elif ext in ("wav", "aiff", "aif"):
        # WAV/AIFF llevan las etiquetas en un chunk ID3.
        audio = WAVE(ruta) if ext == "wav" else AIFF(ruta)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.setall("TCON", [TCON(encoding=3, text=[genero])])
        audio.save()

    else:
        raise ValueError(f"Formato no soportado para escritura: {ext}")


# Correspondencia campo interno -> clave "easy" de mutagen (común a formatos).
_CAMPO_A_EASY = {"artista": "artist", "titulo": "title", "album": "album"}


def escribir_campo(ruta, campo, valor):
    """
    Escribe artista/título/álbum en la etiqueta del archivo. Lanza excepción si
    falla. Solo toca el campo indicado, nada más.
    """
    clave = _CAMPO_A_EASY.get(campo)
    if not clave:
        raise ValueError(f"Campo no soportado: {campo}")
    valor = valor or ""

    audio = mutagen.File(ruta, easy=True)
    if audio is None:
        raise ValueError("Formato no reconocido para escritura de etiquetas.")
    if audio.tags is None:
        audio.add_tags()
    audio[clave] = valor
    audio.save()


def escribir_bpm(ruta, bpm):
    """
    Escribe el BPM en la etiqueta del archivo. Lanza excepción si falla.
    El BPM se guarda como número entero en las etiquetas (convención habitual).
    """
    ext = Path(ruta).suffix.lower().lstrip(".")
    bpm_txt = str(int(round(float(bpm))))

    if ext == "mp3":
        try:
            audio = ID3(ruta)
        except ID3NoHeaderError:
            audio = ID3()
        audio.setall("TBPM", [TBPM(encoding=3, text=[bpm_txt])])
        audio.save(ruta)

    elif ext in ("flac", "ogg"):
        audio = FLAC(ruta) if ext == "flac" else OggVorbis(ruta)
        audio["bpm"] = bpm_txt
        audio.save()

    elif ext == "m4a":
        audio = MP4(ruta)
        audio["tmpo"] = [int(round(float(bpm)))]
        audio.save()

    elif ext in ("wav", "aiff", "aif"):
        audio = WAVE(ruta) if ext == "wav" else AIFF(ruta)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.setall("TBPM", [TBPM(encoding=3, text=[bpm_txt])])
        audio.save()

    else:
        raise ValueError(f"Formato no soportado para escritura: {ext}")
