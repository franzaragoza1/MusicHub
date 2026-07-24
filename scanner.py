"""
scanner.py — Escaneo recursivo de la carpeta de música y lectura de etiquetas.

Usa mutagen para leer artista, título, álbum, género, BPM y duración de cada
archivo. Soporta MP3, FLAC, WAV, AIFF, M4A y OGG.

El escaneo corre en un hilo de fondo; el estado (progreso) se consulta desde
la interfaz.
"""

import os
import threading
from pathlib import Path

import mutagen
from mutagen import MutagenError

import database as db
import generos as generos_mod

# Extensiones soportadas.
EXTENSIONES = {".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".ogg"}

# Estado compartido del escaneo (lo lee la interfaz).
estado = {
    "activo": False,
    "total": 0,
    "procesados": 0,
    "mensaje": "",
    "carpeta": "",
}
_estado_lock = threading.Lock()


def _set_estado(**kwargs):
    with _estado_lock:
        estado.update(kwargs)


def get_estado():
    with _estado_lock:
        return dict(estado)


def _primer_valor(tags, claves):
    """Devuelve el primer valor no vacío entre varias claves posibles."""
    for clave in claves:
        if clave in tags:
            val = tags[clave]
            if isinstance(val, list):
                val = val[0] if val else None
            if val not in (None, ""):
                return str(val).strip()
    return None


def _leer_bpm(audio):
    """
    Lee el BPM de las etiquetas según el formato.
    ID3 -> TBPM ; Vorbis(FLAC/OGG) -> 'bpm' ; MP4 -> 'tmpo'.
    """
    try:
        tags = audio.tags
        if tags is None:
            return None
        # ID3 (MP3, WAV, AIFF con ID3)
        if hasattr(tags, "getall"):
            frames = tags.getall("TBPM")
            if frames:
                try:
                    return float(str(frames[0]))
                except (ValueError, IndexError):
                    pass
        # Vorbis comments (FLAC / OGG)
        for clave in ("bpm", "BPM", "tempo"):
            if clave in tags:
                v = tags[clave]
                if isinstance(v, list):
                    v = v[0] if v else None
                try:
                    return float(str(v))
                except (ValueError, TypeError):
                    pass
        # MP4 (M4A)
        if "tmpo" in tags:
            v = tags["tmpo"]
            if isinstance(v, list):
                v = v[0] if v else None
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    except Exception:
        return None
    return None


def leer_metadatos(ruta):
    """Lee los metadatos de un archivo. Devuelve un dict listo para la BD."""
    p = Path(ruta)
    datos = {
        "ruta": str(p),
        "artista": None,
        "titulo": None,
        "album": None,
        "genero": None,
        "bpm": None,
        "bpm_origen": "ninguno",
        "duracion": None,
        "formato": p.suffix.lower().lstrip("."),
        "carpeta": str(p.parent),
        "mtime": None,
    }
    try:
        datos["mtime"] = os.path.getmtime(ruta)
    except OSError:
        pass

    try:
        audio = mutagen.File(ruta, easy=True)
    except (MutagenError, Exception):
        audio = None

    if audio is not None:
        tags = audio.tags or {}
        datos["artista"] = _primer_valor(tags, ["artist", "albumartist", "ARTIST"])
        datos["titulo"] = _primer_valor(tags, ["title", "TITLE"])
        datos["album"] = _primer_valor(tags, ["album", "ALBUM"])
        datos["genero"] = generos_mod.normalizar(_primer_valor(tags, ["genre", "GENRE"]))
        if audio.info is not None:
            datos["duracion"] = getattr(audio.info, "length", None)

    # El BPM se lee mejor con la vista "cruda" (no easy).
    try:
        audio_raw = mutagen.File(ruta)
        if audio_raw is not None:
            bpm = _leer_bpm(audio_raw)
            if bpm and bpm > 0:
                datos["bpm"] = round(bpm, 1)
                datos["bpm_origen"] = "etiqueta"
            if datos["duracion"] is None and audio_raw.info is not None:
                datos["duracion"] = getattr(audio_raw.info, "length", None)
    except (MutagenError, Exception):
        pass

    # Si no hay título, usar el nombre del archivo como último recurso.
    if not datos["titulo"]:
        datos["titulo"] = p.stem

    return datos


def _escanear_worker(carpeta):
    """
    Recorre la carpeta y vuelca los metadatos en la BD.

    Escaneo INCREMENTAL: los archivos que ya estaban y no han cambiado (misma
    fecha de modificación) no se vuelven a leer, así los reescaneos son casi
    instantáneos y se respeta todo el trabajo ya hecho (géneros, BPM, tonalidad,
    energía y correcciones manuales, que además upsert_track nunca pisa).
    """
    try:
        _set_estado(activo=True, procesados=0, total=0,
                    mensaje="Buscando archivos...", carpeta=carpeta)

        archivos = []
        for raiz, _dirs, ficheros in os.walk(carpeta):
            for f in ficheros:
                if Path(f).suffix.lower() in EXTENSIONES:
                    archivos.append(os.path.join(raiz, f))

        _set_estado(total=len(archivos), mensaje="Leyendo etiquetas...")

        # Fecha de modificación conocida de cada canción ya guardada.
        mtimes_previos = db.mtimes_existentes()
        # Grafía canónica de cada género ya presente (para no crear variantes).
        canon = db.mapa_canonico()

        rutas = []
        nuevas = 0
        saltadas = 0
        for i, ruta in enumerate(archivos, start=1):
            ruta_norm = str(Path(ruta))
            try:
                mtime_actual = os.path.getmtime(ruta)
            except OSError:
                mtime_actual = None

            previo = mtimes_previos.get(ruta_norm)
            sin_cambios = (
                previo is not None
                and mtime_actual is not None
                and abs(previo - mtime_actual) < 1.0
            )

            if sin_cambios:
                # No ha cambiado: no releemos etiquetas, solo confirmamos que sigue.
                rutas.append(ruta_norm)
                saltadas += 1
            else:
                try:
                    datos = leer_metadatos(ruta)
                    if datos.get("genero"):
                        datos["genero"] = canon.get(
                            generos_mod.clave(datos["genero"]), datos["genero"]
                        )
                    db.upsert_track(datos)
                    rutas.append(datos["ruta"])
                    nuevas += 1
                except Exception as e:
                    # Un archivo problemático no debe romper todo el escaneo.
                    print(f"[scanner] Error con {ruta}: {e}")
            _set_estado(procesados=i)

        db.marcar_inexistentes(rutas)
        _set_estado(
            mensaje=(
                f"Escaneo completo: {len(rutas)} canciones "
                f"({nuevas} nuevas o modificadas, {saltadas} sin cambios)."
            )
        )
    finally:
        _set_estado(activo=False)


def iniciar_escaneo(carpeta):
    """Lanza el escaneo en un hilo. Devuelve False si ya hay uno en marcha."""
    with _estado_lock:
        if estado["activo"]:
            return False
        # Marcamos activo con el lock para evitar carreras con quien consulta.
        estado["activo"] = True
        estado["mensaje"] = "Preparando..."
    hilo = threading.Thread(target=_escanear_worker, args=(carpeta,), daemon=True)
    hilo.start()
    return True
