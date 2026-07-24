"""
bpm.py — Cálculo del BPM (velocidad) por análisis de audio, en segundo plano.

Intenta usar librosa (más preciso). Si librosa no está disponible o falla al
importar (por ejemplo por problemas de numba en algún Python), cae en un
detector propio más simple basado en autocorrelación de la envolvente de
energía, suficiente para música electrónica 4x4.

El cálculo corre en un hilo con una cola de trabajos; la interfaz consulta el
progreso.
"""

import threading

import numpy as np
import soundfile as sf

import database as db
import tags
import key as key_mod
import energy as energy_mod

# Intento de importar librosa de forma perezosa y tolerante a fallos.
try:
    import librosa  # noqa: F401
    _HAY_LIBROSA = True
except Exception:  # pragma: no cover - depende del entorno
    _HAY_LIBROSA = False

# Estado compartido del cálculo (lo lee la interfaz).
estado = {
    "activo": False,
    "total": 0,
    "procesados": 0,
    "mensaje": "",
}
_estado_lock = threading.Lock()


def _set_estado(**kwargs):
    with _estado_lock:
        estado.update(kwargs)


def get_estado():
    with _estado_lock:
        return dict(estado)


def _cargar_audio_mono(ruta, sr_objetivo=22050):
    """Carga el audio como mono a una frecuencia de muestreo conocida."""
    if _HAY_LIBROSA:
        import librosa
        y, sr = librosa.load(ruta, sr=sr_objetivo, mono=True)
        return y, sr
    # Respaldo con soundfile (decodifica WAV/FLAC/OGG; MP3/M4A según libsndfile).
    y, sr = sf.read(ruta, always_2d=True)
    y = y.mean(axis=1)  # a mono
    if sr != sr_objetivo:
        # Remuestreo lineal sencillo.
        n = int(round(len(y) * sr_objetivo / sr))
        if n > 0:
            y = np.interp(
                np.linspace(0, len(y), n, endpoint=False),
                np.arange(len(y)),
                y,
            )
            sr = sr_objetivo
    return y.astype(np.float32), sr


def _bpm_fallback(y, sr):
    """
    Detector de BPM propio: autocorrelación de la envolvente de energía.
    Devuelve un BPM en el rango típico de DJ (70-190) o None.
    """
    if len(y) < sr * 5:
        return None
    # Envolvente de energía por ventanas (~10 ms).
    hop = int(sr * 0.01)
    if hop < 1:
        return None
    n_frames = len(y) // hop
    energia = np.array([
        np.sum(y[i * hop:(i + 1) * hop] ** 2) for i in range(n_frames)
    ])
    # Flujo de energía (solo aumentos): resalta los golpes.
    flujo = np.diff(energia)
    flujo[flujo < 0] = 0
    if flujo.std() == 0:
        return None
    flujo = flujo - flujo.mean()

    fps = sr / hop  # frames por segundo de la envolvente
    # Buscamos el periodo entre 60/190 y 60/70 segundos.
    min_lag = int(fps * 60 / 190)
    max_lag = int(fps * 60 / 70)
    max_lag = min(max_lag, len(flujo) - 1)
    if max_lag <= min_lag:
        return None

    ac = np.correlate(flujo, flujo, mode="full")
    ac = ac[len(ac) // 2:]  # solo lags positivos
    ventana = ac[min_lag:max_lag]
    if len(ventana) == 0:
        return None
    mejor_lag = min_lag + int(np.argmax(ventana))
    if mejor_lag == 0:
        return None
    bpm = 60.0 * fps / mejor_lag
    # Normalizar al rango típico doblando/dividiendo.
    while bpm < 90:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    return round(bpm, 1)


def _bpm_de_audio(y, sr):
    """Calcula el BPM a partir de audio ya cargado. Devuelve float o None."""
    if y is None or len(y) == 0:
        return None
    if _HAY_LIBROSA:
        try:
            import librosa
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            tempo = float(np.atleast_1d(tempo)[0])
            if tempo and tempo > 0:
                return round(tempo, 1)
        except Exception as e:
            print(f"[bpm] librosa falló, uso respaldo: {e}")
    return _bpm_fallback(y, sr)


def calcular_bpm(ruta):
    """Calcula el BPM de un archivo (carga el audio). Devuelve float o None."""
    try:
        y, sr = _cargar_audio_mono(ruta)
    except Exception as e:
        print(f"[bpm] No se pudo decodificar {ruta}: {e}")
        return None
    return _bpm_de_audio(y, sr)


def _worker(escribir_en_archivo=True):
    try:
        pendientes = db.tracks_sin_analizar()
        _set_estado(activo=True, total=len(pendientes), procesados=0,
                    mensaje="Analizando audio (BPM + tonalidad + energía)...")

        hubo_energia_nueva = False

        for i, tr in enumerate(pendientes, start=1):
            necesita_bpm = tr["bpm"] is None and tr["bpm_origen"] != "no_calculable"
            necesita_ton = tr["tonalidad"] is None and tr["tonalidad_origen"] != "no_calculable"
            necesita_energia = tr["e_rms"] is None and tr["energia_origen"] != "no_calculable"

            # Cargamos el audio UNA sola vez y calculamos lo que falte.
            y, sr = None, None
            if necesita_bpm or necesita_ton or necesita_energia:
                try:
                    y, sr = _cargar_audio_mono(tr["ruta"])
                except Exception as e:
                    print(f"[analisis] No se pudo decodificar {tr['ruta']}: {e}")

            if necesita_bpm:
                bpm = _bpm_de_audio(y, sr) if y is not None else None
                if bpm:
                    db.actualizar_bpm(tr["id"], bpm, origen="calculado")
                    if escribir_en_archivo:
                        try:
                            tags.escribir_bpm(tr["ruta"], bpm)
                            # Refrescar la fecha guardada: escribir cambió el archivo
                            # y no queremos que el próximo escaneo lo relea por eso.
                            db.refrescar_mtime(tr["id"], tr["ruta"])
                        except Exception as e:
                            print(f"[bpm] No se pudo escribir BPM en {tr['ruta']}: {e}")
                else:
                    db.actualizar_bpm(tr["id"], None, origen="no_calculable")

            if necesita_ton:
                ton = key_mod.detectar_tonalidad(y, sr) if y is not None else None
                if ton:
                    db.actualizar_tonalidad(tr["id"], ton, origen="calculado")
                else:
                    db.actualizar_tonalidad(tr["id"], None, origen="no_calculable")

            if necesita_energia:
                metricas = energy_mod.metricas_energia(y, sr) if y is not None else None
                if metricas:
                    db.actualizar_metricas_energia(
                        tr["id"], metricas["rms"], metricas["onset"], metricas["brillo"]
                    )
                    hubo_energia_nueva = True
                else:
                    db.actualizar_energia(tr["id"], None, origen="no_calculable")

            _set_estado(procesados=i)

        if hubo_energia_nueva:
            _set_estado(mensaje="Calibrando energía de la colección...")
            energy_mod.recalibrar()

        _set_estado(mensaje="Análisis completado.")
    finally:
        _set_estado(activo=False)


def iniciar_calculo(escribir_en_archivo=True):
    """Lanza el cálculo en un hilo. Devuelve False si ya hay uno en marcha."""
    with _estado_lock:
        if estado["activo"]:
            return False
        # Marcamos activo aquí (con el lock) para evitar que un consultor del
        # estado vea 'inactivo' antes de que el hilo arranque.
        estado["activo"] = True
        estado["mensaje"] = "Preparando..."
    hilo = threading.Thread(target=_worker, args=(escribir_en_archivo,), daemon=True)
    hilo.start()
    return True
