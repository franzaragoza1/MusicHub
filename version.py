"""
version.py — Versión de MusicHub y datos para el comprobador de actualizaciones.

Al publicar una versión nueva:
  1. Sube el número de VERSION aquí (ej. "1.0.1").
  2. Haz commit y crea una etiqueta igual con una "v" delante:
        git tag v1.0.1 && git push --tags
     Eso hace que GitHub Actions compile y publique una Release.
  3. Las apps ya instaladas veran que hay una version mas nueva y lo avisaran.
"""

VERSION = "1.0.0"

# Repositorio de GitHub desde donde se comprueban/descargan las versiones.
# El comprobador solo funciona si las Releases son PUBLICAS.
GITHUB_REPO = "franzaragoza1/MusicHub"
