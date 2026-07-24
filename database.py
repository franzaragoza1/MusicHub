"""
database.py — Capa de acceso a SQLite para MusicHub.

Guarda la biblioteca de canciones, los géneros corregidos, las listas de
reproducción y los ajustes (como la carpeta de música elegida).

Todo es 100% local. La base de datos se guarda en una carpeta de datos del
usuario (%LOCALAPPDATA%\\MusicHub en Windows), SEPARADA de los archivos del
programa, para que sea imposible perderla al actualizar o mover el programa.
"""

import sqlite3
import os
import sys
import shutil
import threading
from datetime import datetime


def _ruta_base_datos():
    """
    Carpeta estable de datos del usuario, fuera del directorio del programa y
    en la ubicación convencional de cada sistema:
      - Windows: %LOCALAPPDATA%\\MusicHub
      - macOS:   ~/Library/Application Support/MusicHub
      - Linux:   $XDG_DATA_HOME/MusicHub  (o ~/.local/share/MusicHub)
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") \
            or os.path.expanduser("~")
        carpeta = os.path.join(base, "MusicHub")
    elif sys.platform == "darwin":
        carpeta = os.path.join(os.path.expanduser("~"),
                               "Library", "Application Support", "MusicHub")
    else:
        base = os.environ.get("XDG_DATA_HOME") \
            or os.path.join(os.path.expanduser("~"), ".local", "share")
        carpeta = os.path.join(base, "MusicHub")
    try:
        os.makedirs(carpeta, exist_ok=True)
    except Exception:
        carpeta = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(carpeta, "musichub.db")


DB_PATH = _ruta_base_datos()

# Migración: si existía una base de datos antigua junto al programa y todavía no
# hay una en la carpeta de datos, la traemos para no perder nada.
_legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "musichub.db")
if os.path.exists(_legacy) and not os.path.exists(DB_PATH) and _legacy != DB_PATH:
    try:
        shutil.copy2(_legacy, DB_PATH)
    except Exception:
        pass

# SQLite + hilos: usamos check_same_thread=False y un lock para escribir con
# seguridad desde el hilo de escaneo / cálculo de BPM y desde Flask a la vez.
_lock = threading.RLock()
_conn = None


def get_conn():
    """Devuelve la conexión única (la crea la primera vez)."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def init_db():
    """Crea las tablas si no existen."""
    with _lock:
        conn = get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                clave TEXT PRIMARY KEY,
                valor TEXT
            );

            CREATE TABLE IF NOT EXISTS tracks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ruta        TEXT UNIQUE NOT NULL,
                artista     TEXT,
                titulo      TEXT,
                album       TEXT,
                genero      TEXT,
                bpm         REAL,
                bpm_origen  TEXT DEFAULT 'ninguno',  -- etiqueta | calculado | ninguno
                duracion    REAL,                    -- segundos
                formato     TEXT,
                carpeta     TEXT,                    -- carpeta que contiene el archivo
                tonalidad   TEXT,                    -- tonalidad en notación Camelot (ej: 8A)
                tonalidad_origen TEXT DEFAULT 'ninguno', -- etiqueta | calculado | ninguno | no_calculable
                energia     INTEGER,                 -- energía/intensidad 1-10
                energia_origen TEXT DEFAULT 'ninguno', -- calculado | manual | ninguno | no_calculable
                e_rms       REAL,                    -- métrica en bruto: sonoridad media
                e_onset     REAL,                    -- métrica en bruto: densidad de onsets (ritmo)
                e_cent      REAL,                    -- métrica en bruto: centroide espectral (brillo)
                mtime       REAL,                    -- fecha de modificación del archivo
                existe      INTEGER DEFAULT 1,       -- 0 si el archivo ya no está
                fecha_escaneo TEXT
            );

            CREATE TABLE IF NOT EXISTS playlists (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre  TEXT UNIQUE NOT NULL,
                fecha   TEXT
            );

            CREATE TABLE IF NOT EXISTS playlist_tracks (
                playlist_id INTEGER NOT NULL,
                track_id    INTEGER NOT NULL,
                orden       INTEGER NOT NULL,
                PRIMARY KEY (playlist_id, track_id),
                FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
                FOREIGN KEY (track_id)    REFERENCES tracks(id)    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tracks_genero  ON tracks(genero);
            CREATE INDEX IF NOT EXISTS idx_tracks_artista ON tracks(artista);
            CREATE INDEX IF NOT EXISTS idx_tracks_bpm     ON tracks(bpm);
            """
        )
        # Migración: añadir columnas nuevas si la base de datos es antigua.
        columnas = [r["name"] for r in conn.execute("PRAGMA table_info(tracks)").fetchall()]
        if "carpeta" not in columnas:
            conn.execute("ALTER TABLE tracks ADD COLUMN carpeta TEXT")
        if "tonalidad" not in columnas:
            conn.execute("ALTER TABLE tracks ADD COLUMN tonalidad TEXT")
        if "tonalidad_origen" not in columnas:
            conn.execute("ALTER TABLE tracks ADD COLUMN tonalidad_origen TEXT DEFAULT 'ninguno'")
        if "energia" not in columnas:
            conn.execute("ALTER TABLE tracks ADD COLUMN energia INTEGER")
        if "energia_origen" not in columnas:
            conn.execute("ALTER TABLE tracks ADD COLUMN energia_origen TEXT DEFAULT 'ninguno'")
        if "e_rms" not in columnas:
            conn.execute("ALTER TABLE tracks ADD COLUMN e_rms REAL")
        if "e_onset" not in columnas:
            conn.execute("ALTER TABLE tracks ADD COLUMN e_onset REAL")
        if "e_cent" not in columnas:
            conn.execute("ALTER TABLE tracks ADD COLUMN e_cent REAL")
        conn.commit()


# ----------------------------------------------------------------------------
# Ajustes (carpeta de música, etc.)
# ----------------------------------------------------------------------------
def set_setting(clave, valor):
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO settings (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (clave, valor),
        )
        conn.commit()


def get_setting(clave, defecto=None):
    with _lock:
        conn = get_conn()
        row = conn.execute("SELECT valor FROM settings WHERE clave=?", (clave,)).fetchone()
        return row["valor"] if row else defecto


# ----------------------------------------------------------------------------
# Tracks
# ----------------------------------------------------------------------------
def upsert_track(datos):
    """
    Inserta o actualiza una canción por su ruta.

    `datos` es un dict con: ruta, artista, titulo, album, genero, bpm,
    bpm_origen, duracion, formato, mtime.

    Importante: NO pisa el género ni el BPM ya guardados en la base de datos
    si el archivo no aporta uno nuevo, para no perder correcciones manuales.
    """
    with _lock:
        conn = get_conn()
        existente = conn.execute(
            "SELECT id, genero, bpm, bpm_origen FROM tracks WHERE ruta=?",
            (datos["ruta"],),
        ).fetchone()

        ahora = datetime.now().isoformat(timespec="seconds")

        if existente is None:
            conn.execute(
                """INSERT INTO tracks
                   (ruta, artista, titulo, album, genero, bpm, bpm_origen,
                    duracion, formato, carpeta, mtime, existe, fecha_escaneo)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (
                    datos["ruta"], datos.get("artista"), datos.get("titulo"),
                    datos.get("album"), datos.get("genero"), datos.get("bpm"),
                    datos.get("bpm_origen", "ninguno"), datos.get("duracion"),
                    datos.get("formato"), datos.get("carpeta"), datos.get("mtime"), ahora,
                ),
            )
        else:
            # Conservamos género/BPM de la BD si ya existían (correcciones del
            # usuario o BPM calculado). Solo tomamos los del archivo para
            # rellenar huecos.
            genero = existente["genero"] or datos.get("genero")
            if existente["bpm"] is not None:
                bpm = existente["bpm"]
                bpm_origen = existente["bpm_origen"]
            else:
                bpm = datos.get("bpm")
                bpm_origen = datos.get("bpm_origen", "ninguno")

            conn.execute(
                """UPDATE tracks SET
                   artista=?, titulo=?, album=?, genero=?, bpm=?, bpm_origen=?,
                   duracion=?, formato=?, carpeta=?, mtime=?, existe=1, fecha_escaneo=?
                   WHERE ruta=?""",
                (
                    datos.get("artista"), datos.get("titulo"), datos.get("album"),
                    genero, bpm, bpm_origen, datos.get("duracion"),
                    datos.get("formato"), datos.get("carpeta"), datos.get("mtime"),
                    ahora, datos["ruta"],
                ),
            )
        conn.commit()


def mtimes_existentes():
    """
    Devuelve {ruta: mtime} de todas las canciones ya en la base de datos.
    Lo usa el escaneo incremental para saltarse los archivos que no han cambiado
    (misma fecha de modificación) y no volver a leer sus etiquetas.
    """
    with _lock:
        conn = get_conn()
        rows = conn.execute("SELECT ruta, mtime FROM tracks").fetchall()
        return {r["ruta"]: r["mtime"] for r in rows}


def marcar_inexistentes(rutas_encontradas):
    """Marca como no existentes las canciones cuyo archivo ya no está."""
    with _lock:
        conn = get_conn()
        conn.execute("UPDATE tracks SET existe=0")
        # Reactivar las que sí se encontraron.
        for ruta in rutas_encontradas:
            conn.execute("UPDATE tracks SET existe=1 WHERE ruta=?", (ruta,))
        conn.commit()


def listar_tracks(solo_existentes=True):
    with _lock:
        conn = get_conn()
        sql = "SELECT * FROM tracks"
        if solo_existentes:
            sql += " WHERE existe=1"
        sql += " ORDER BY artista COLLATE NOCASE, titulo COLLATE NOCASE"
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_track(track_id):
    with _lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
        return dict(row) if row else None


def actualizar_genero(track_id, genero):
    with _lock:
        conn = get_conn()
        conn.execute("UPDATE tracks SET genero=? WHERE id=?", (genero, track_id))
        conn.commit()


def actualizar_mtime(track_id, mtime):
    with _lock:
        conn = get_conn()
        conn.execute("UPDATE tracks SET mtime=? WHERE id=?", (mtime, track_id))
        conn.commit()


def refrescar_mtime(track_id, ruta):
    """
    Actualiza la fecha guardada a la real del archivo. Se llama DESPUÉS de que el
    programa escriba una etiqueta dentro del archivo (género, BPM, nombre...),
    porque esa escritura cambia la fecha en disco: si no la refrescáramos, el
    próximo escaneo creería que el archivo cambió y lo releería sin necesidad.
    """
    try:
        mt = os.path.getmtime(ruta)
    except OSError:
        return
    actualizar_mtime(track_id, mt)


def actualizar_bpm(track_id, bpm, origen="calculado"):
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE tracks SET bpm=?, bpm_origen=? WHERE id=?", (bpm, origen, track_id)
        )
        conn.commit()


def actualizar_tonalidad(track_id, tonalidad, origen="calculado"):
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE tracks SET tonalidad=?, tonalidad_origen=? WHERE id=?",
            (tonalidad, origen, track_id),
        )
        conn.commit()


def actualizar_metricas_energia(track_id, rms, onset, cent):
    """Guarda las métricas en bruto (aún no la nota 1-10, que se calcula al recalibrar)."""
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE tracks SET e_rms=?, e_onset=?, e_cent=? WHERE id=?",
            (rms, onset, cent, track_id),
        )
        conn.commit()


def actualizar_energia(track_id, valor, origen="calculado"):
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE tracks SET energia=?, energia_origen=? WHERE id=?",
            (valor, origen, track_id),
        )
        conn.commit()


def tracks_con_metricas_energia():
    """
    Todas las pistas existentes con métricas en bruto ya calculadas (para
    recalibrar la escala 1-10 de toda la colección).
    """
    with _lock:
        conn = get_conn()
        rows = conn.execute(
            """SELECT id, e_rms, e_onset, e_cent, energia_origen FROM tracks
               WHERE existe=1 AND e_rms IS NOT NULL"""
        ).fetchall()
        return [dict(r) for r in rows]


# Campos de texto editables desde la interfaz (además del género).
CAMPOS_EDITABLES = {"artista", "titulo", "album"}


def actualizar_campo(track_id, campo, valor):
    """Actualiza un campo de texto (artista, titulo o album) de forma segura."""
    if campo not in CAMPOS_EDITABLES:
        raise ValueError(f"Campo no editable: {campo}")
    with _lock:
        conn = get_conn()
        # El nombre de columna proviene de una lista blanca, no del usuario.
        conn.execute(f"UPDATE tracks SET {campo}=? WHERE id=?", (valor, track_id))
        conn.commit()


def generos_existentes():
    """Lista de géneros distintos ya presentes (para autocompletar)."""
    with _lock:
        conn = get_conn()
        rows = conn.execute(
            "SELECT DISTINCT genero FROM tracks "
            "WHERE genero IS NOT NULL AND genero <> '' ORDER BY genero COLLATE NOCASE"
        ).fetchall()
        return [r["genero"] for r in rows]


def tracks_sin_bpm():
    """
    IDs de canciones existentes sin BPM que aún no se han intentado calcular.
    Se excluyen las marcadas como 'no_calculable' para no reintentarlas en bucle.
    """
    with _lock:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, ruta FROM tracks "
            "WHERE existe=1 AND bpm IS NULL AND bpm_origen <> 'no_calculable'"
        ).fetchall()
        return [dict(r) for r in rows]


def tracks_sin_analizar():
    """
    Pistas existentes a las que les falta BPM, tonalidad o métricas de
    energía (para el análisis de audio en segundo plano). Se excluye lo ya
    marcado como no calculable.
    """
    with _lock:
        conn = get_conn()
        rows = conn.execute(
            """SELECT id, ruta, bpm, bpm_origen, tonalidad, tonalidad_origen,
                      e_rms, energia_origen
               FROM tracks
               WHERE existe=1 AND (
                   (bpm IS NULL AND bpm_origen <> 'no_calculable') OR
                   (tonalidad IS NULL AND tonalidad_origen <> 'no_calculable') OR
                   (e_rms IS NULL AND energia_origen <> 'no_calculable')
               )"""
        ).fetchall()
        return [dict(r) for r in rows]


# ----------------------------------------------------------------------------
# Listas de reproducción
# ----------------------------------------------------------------------------
def crear_o_reemplazar_playlist(nombre, track_ids):
    """Crea (o sobrescribe) una lista con los track_ids en el orden dado."""
    with _lock:
        conn = get_conn()
        ahora = datetime.now().isoformat(timespec="seconds")
        row = conn.execute("SELECT id FROM playlists WHERE nombre=?", (nombre,)).fetchone()
        if row:
            pid = row["id"]
            conn.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (pid,))
            conn.execute("UPDATE playlists SET fecha=? WHERE id=?", (ahora, pid))
        else:
            cur = conn.execute(
                "INSERT INTO playlists (nombre, fecha) VALUES (?, ?)", (nombre, ahora)
            )
            pid = cur.lastrowid
        for orden, tid in enumerate(track_ids):
            conn.execute(
                "INSERT INTO playlist_tracks (playlist_id, track_id, orden) VALUES (?,?,?)",
                (pid, tid, orden),
            )
        conn.commit()
        return pid


def listar_playlists():
    with _lock:
        conn = get_conn()
        rows = conn.execute(
            """SELECT p.id, p.nombre, p.fecha, COUNT(pt.track_id) AS num
               FROM playlists p
               LEFT JOIN playlist_tracks pt ON pt.playlist_id = p.id
               GROUP BY p.id ORDER BY p.nombre COLLATE NOCASE"""
        ).fetchall()
        return [dict(r) for r in rows]


def get_playlist(playlist_id):
    """Devuelve la lista con sus canciones en orden."""
    with _lock:
        conn = get_conn()
        pl = conn.execute("SELECT * FROM playlists WHERE id=?", (playlist_id,)).fetchone()
        if not pl:
            return None
        tracks = conn.execute(
            """SELECT t.* FROM playlist_tracks pt
               JOIN tracks t ON t.id = pt.track_id
               WHERE pt.playlist_id=? ORDER BY pt.orden""",
            (playlist_id,),
        ).fetchall()
        return {"id": pl["id"], "nombre": pl["nombre"], "fecha": pl["fecha"],
                "tracks": [dict(t) for t in tracks]}


def borrar_playlist(playlist_id):
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))
        conn.commit()
