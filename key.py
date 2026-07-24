"""
key.py — Detección de la tonalidad musical (key) por análisis de audio.

Estima la tonalidad con el método de Krumhansl-Schmuckler (correlación del
cromagrama medio con los perfiles de tono mayor/menor) y la devuelve en
notación Camelot (ej: "8A", "5B"), que es la que usan los DJ para mezcla
armónica y que muestran Rekordbox y Traktor.

Requiere librosa. Si no está disponible, devuelve None (la tonalidad se queda
vacía, igual que un BPM no calculable).
"""

import numpy as np

# Perfiles de Krumhansl-Schmuckler (mayor y menor).
_PERFIL_MAYOR = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
_PERFIL_MENOR = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)

# Camelot por clase de tono (0=Do ... 11=Si).
_CAMELOT_MAYOR = {
    0: "8B", 1: "3B", 2: "10B", 3: "5B", 4: "12B", 5: "7B",
    6: "2B", 7: "9B", 8: "4B", 9: "11B", 10: "6B", 11: "1B",
}
_CAMELOT_MENOR = {
    0: "5A", 1: "12A", 2: "7A", 3: "2A", 4: "9A", 5: "4A",
    6: "11A", 7: "6A", 8: "1A", 9: "8A", 10: "3A", 11: "10A",
}


def detectar_tonalidad(y, sr):
    """
    Devuelve la tonalidad en Camelot (str) a partir de la señal de audio mono,
    o None si no se pudo (o si librosa no está disponible).
    """
    try:
        import librosa
    except Exception:
        return None

    if y is None or len(y) < sr:
        return None

    try:
        # Cromagrama (energía por clase de tono) promediado en el tiempo.
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        perfil = chroma.mean(axis=1)
        if perfil.sum() == 0:
            return None
        perfil = perfil - perfil.mean()

        mejor_corr = -2.0
        mejor_tono = 0
        mejor_modo = "mayor"
        pm = _PERFIL_MAYOR - _PERFIL_MAYOR.mean()
        pmen = _PERFIL_MENOR - _PERFIL_MENOR.mean()

        for despl in range(12):
            rot = np.roll(perfil, -despl)
            corr_may = _correlacion(rot, pm)
            corr_men = _correlacion(rot, pmen)
            if corr_may > mejor_corr:
                mejor_corr, mejor_tono, mejor_modo = corr_may, despl, "mayor"
            if corr_men > mejor_corr:
                mejor_corr, mejor_tono, mejor_modo = corr_men, despl, "menor"

        tabla = _CAMELOT_MAYOR if mejor_modo == "mayor" else _CAMELOT_MENOR
        return tabla[mejor_tono]
    except Exception:
        return None


def _correlacion(a, b):
    da = np.sqrt((a * a).sum())
    db = np.sqrt((b * b).sum())
    if da == 0 or db == 0:
        return -2.0
    return float((a * b).sum() / (da * db))
