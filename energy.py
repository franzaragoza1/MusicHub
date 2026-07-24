"""
energy.py — Estimación de la "energía" (intensidad) de un tema, 1-10.

Combina tres métricas de audio:
  - RMS (sonoridad media)          -> peso 50%
  - Densidad de onsets (ritmo)     -> peso 30%
  - Centroide espectral (brillo)   -> peso 20%

Cada métrica se calcula en bruto por tema y se normaliza por PERCENTIL dentro
de la propia colección (no contra un valor absoluto), porque "energía" es
relativo: un 8/10 en una colección de ambient no suena igual que un 8/10 en
una de hardstyle. Por eso, cada vez que se analiza música nueva, se
recalibra la escala 1-10 de toda la colección.

Las correcciones manuales del usuario (energia_origen='manual') nunca se
sobreescriben al recalibrar.
"""

import numpy as np

import database as db

PESO_RMS = 0.5
PESO_ONSET = 0.3
PESO_BRILLO = 0.2


def metricas_energia(y, sr):
    """
    Calcula las tres métricas en bruto a partir de audio ya cargado.
    Devuelve dict {rms, onset, brillo} o None si no se pudo (sin librosa o
    audio vacío).
    """
    if y is None or len(y) == 0:
        return None
    try:
        import librosa
    except Exception:
        return None

    try:
        rms = float(librosa.feature.rms(y=y).mean())
        onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
        duracion = len(y) / sr
        onset_rate = float(len(onsets) / duracion) if duracion > 0 else 0.0
        centroide = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())
        return {"rms": rms, "onset": onset_rate, "brillo": centroide}
    except Exception:
        return None


def _percentil(valores, i):
    """Posición relativa (0..1) del elemento i dentro de la lista ordenada."""
    n = len(valores)
    if n <= 1:
        return 0.5
    orden = sorted(range(n), key=lambda k: valores[k])
    rango = orden.index(i)
    return rango / (n - 1)


def recalibrar():
    """
    Recalcula la escala 1-10 de TODA la colección a partir de las métricas
    en bruto guardadas, sin tocar las pistas corregidas a mano.
    """
    filas = db.tracks_con_metricas_energia()
    candidatas = [f for f in filas if f["e_rms"] is not None]
    if not candidatas:
        return

    rms_vals = [f["e_rms"] for f in candidatas]
    onset_vals = [f["e_onset"] for f in candidatas]
    brillo_vals = [f["e_cent"] for f in candidatas]

    for i, f in enumerate(candidatas):
        if f["energia_origen"] == "manual":
            continue
        p_rms = _percentil(rms_vals, i)
        p_onset = _percentil(onset_vals, i)
        p_brillo = _percentil(brillo_vals, i)
        score = PESO_RMS * p_rms + PESO_ONSET * p_onset + PESO_BRILLO * p_brillo
        valor = max(1, min(10, round(1 + score * 9)))
        db.actualizar_energia(f["id"], valor, origen="calculado")
