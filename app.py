"""
app.py — Servidor local de MusicHub.

Arranca un servidor web en 127.0.0.1 (solo tu ordenador) y sirve la interfaz.
No accede a internet en ningún momento.

Ejecuta:  python app.py
Luego abre:  http://127.0.0.1:5000
(El lanzador MusicHub.bat abre el navegador automáticamente.)
"""

import os
import re
import sys
import subprocess
import threading
import webbrowser

from flask import Flask, request, jsonify, render_template, send_from_directory, send_file, abort, Response, url_for

import database as db
import scanner
import bpm as bpm_mod
import tags
import cover as cover_mod
import exporters
import ai
import actualizaciones
from version import VERSION

def _ruta_recurso(rel):
    """
    Ruta a un recurso (templates/, static/) que funciona tanto ejecutando el
    código como dentro de un ejecutable de PyInstaller (donde los datos van a
    una carpeta temporal sys._MEIPASS).
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


app = Flask(
    __name__,
    template_folder=_ruta_recurso("templates"),
    static_folder=_ruta_recurso("static"),
)

PUERTO = 5000

# Referencia a la ventana pywebview (si la hay), para usar sus diálogos nativos.
MAIN_WINDOW = None


@app.context_processor
def _inyectar_version_estaticos():
    """
    Da a las plantillas una función asset('x.js') que añade ?v=<fecha> a la URL.
    Así, cada vez que se actualiza el .js o el .css, la URL cambia y el navegador
    coge sí o sí la última versión (nunca se queda con una copia vieja en caché).
    """
    def asset(filename):
        try:
            v = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            v = 0
        return f"{url_for('static', filename=filename)}?v={v}"
    return {"asset": asset}


# ----------------------------------------------------------------------------
# Página principal
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ----------------------------------------------------------------------------
# Ajustes / carpeta de música
# ----------------------------------------------------------------------------
@app.route("/api/carpeta", methods=["GET"])
def get_carpeta():
    return jsonify({"carpeta": db.get_setting("carpeta_musica", "")})


def _pedir_carpeta_nativa():
    """
    Abre un diálogo nativo para elegir carpeta. Devuelve la ruta, o None si se
    cancela / no se puede. Usa el diálogo de pywebview (funciona empaquetado);
    si no hay ventana pywebview (modo navegador desde código), cae a un pequeño
    ayudante tkinter en un subproceso.
    """
    if MAIN_WINDOW is not None:
        try:
            import webview
            res = MAIN_WINDOW.create_file_dialog(webview.FOLDER_DIALOG)
            if not res:
                return None
            return res[0] if isinstance(res, (list, tuple)) else res
        except Exception as e:
            print(f"[carpeta] El diálogo nativo de pywebview falló: {e}")
            # seguimos al respaldo tkinter

    # Empaquetado sin ventana pywebview: no hay intérprete para el ayudante.
    if getattr(sys, "frozen", False):
        return None

    ayudante = os.path.join(os.path.dirname(os.path.abspath(__file__)), "elegir_carpeta.py")
    try:
        res = subprocess.run(
            [sys.executable, ayudante],
            capture_output=True, text=True, timeout=300,
        )
        return (res.stdout or "").strip() or None
    except Exception as e:
        print(f"[carpeta] El ayudante tkinter falló: {e}")
        return None


@app.route("/api/elegir-carpeta", methods=["POST"])
def elegir_carpeta():
    """Abre el explorador de carpetas nativo y guarda la carpeta elegida."""
    try:
        carpeta = _pedir_carpeta_nativa()
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo abrir el explorador: {e}"}), 500

    if not carpeta:
        # El usuario canceló el diálogo (o no hay diálogo disponible).
        return jsonify({"ok": True, "carpeta": None, "cancelado": True})
    if not os.path.isdir(carpeta):
        return jsonify({"ok": False, "error": "La carpeta elegida no es válida."}), 400

    db.set_setting("carpeta_musica", carpeta)
    return jsonify({"ok": True, "carpeta": carpeta})


@app.route("/api/carpeta", methods=["POST"])
def set_carpeta():
    carpeta = (request.json or {}).get("carpeta", "").strip()
    if not carpeta or not os.path.isdir(carpeta):
        return jsonify({"ok": False, "error": "La carpeta no existe."}), 400
    db.set_setting("carpeta_musica", carpeta)
    return jsonify({"ok": True, "carpeta": carpeta})


# ----------------------------------------------------------------------------
# Escaneo
# ----------------------------------------------------------------------------
@app.route("/api/escanear", methods=["POST"])
def escanear():
    carpeta = db.get_setting("carpeta_musica", "")
    if not carpeta or not os.path.isdir(carpeta):
        return jsonify({"ok": False, "error": "Primero elige una carpeta válida."}), 400
    if not scanner.iniciar_escaneo(carpeta):
        return jsonify({"ok": False, "error": "Ya hay un escaneo en marcha."}), 409
    return jsonify({"ok": True})


@app.route("/api/escaneo/estado")
def escaneo_estado():
    return jsonify(scanner.get_estado())


# ----------------------------------------------------------------------------
# Biblioteca
# ----------------------------------------------------------------------------
@app.route("/api/tracks")
def get_tracks():
    tracks = db.listar_tracks()
    raiz = db.get_setting("carpeta_musica", "") or ""
    # Añadimos a cada canción su subcarpeta relativa a la carpeta raíz, para
    # poder agrupar por carpeta en la interfaz. "" = está en la propia raíz.
    for t in tracks:
        carpeta = t.get("carpeta") or ""
        sub = ""
        if raiz and carpeta:
            try:
                rel = os.path.relpath(carpeta, raiz)
                sub = "" if rel == "." else rel
                # Si la carpeta está fuera de la raíz (empieza por ".."), la dejamos vacía.
                if sub.startswith(".."):
                    sub = ""
            except (ValueError, OSError):
                sub = ""
        t["subcarpeta"] = sub
    return jsonify(tracks)


@app.route("/api/generos")
def get_generos():
    return jsonify(db.generos_existentes())


@app.route("/api/track/<int:track_id>/genero", methods=["POST"])
def set_genero(track_id):
    genero = (request.json or {}).get("genero", "").strip()
    tr = db.get_track(track_id)
    if not tr:
        return jsonify({"ok": False, "error": "Canción no encontrada."}), 404

    db.actualizar_genero(track_id, genero)

    # Intentar escribir también en el archivo. Si falla, avisamos pero el
    # cambio queda guardado en la base de datos.
    aviso = None
    try:
        tags.escribir_genero(tr["ruta"], genero)
        db.refrescar_mtime(track_id, tr["ruta"])
    except Exception as e:
        aviso = f"Guardado en el programa, pero no se pudo escribir en el archivo: {e}"

    return jsonify({"ok": True, "aviso": aviso})


@app.route("/api/track/<int:track_id>/campo", methods=["POST"])
def set_campo(track_id):
    """Edita artista/título/álbum de una canción (BD + etiqueta del archivo)."""
    data = request.json or {}
    campo = (data.get("campo") or "").strip()
    valor = (data.get("valor") or "").strip()
    if campo not in db.CAMPOS_EDITABLES:
        return jsonify({"ok": False, "error": "Campo no editable."}), 400
    tr = db.get_track(track_id)
    if not tr:
        return jsonify({"ok": False, "error": "Canción no encontrada."}), 404

    db.actualizar_campo(track_id, campo, valor)
    aviso = None
    try:
        tags.escribir_campo(tr["ruta"], campo, valor)
        db.refrescar_mtime(track_id, tr["ruta"])
    except Exception as e:
        aviso = f"Guardado en el programa, pero no se pudo escribir en el archivo: {e}"
    return jsonify({"ok": True, "aviso": aviso})


@app.route("/api/track/<int:track_id>/energia", methods=["POST"])
def set_energia(track_id):
    """Corrección manual de la energía (1-10). Esta nota nunca se recalibra sola."""
    data = request.json or {}
    try:
        valor = int(data.get("valor"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "El valor de energía debe ser un número."}), 400
    if not (1 <= valor <= 10):
        return jsonify({"ok": False, "error": "La energía debe estar entre 1 y 10."}), 400
    tr = db.get_track(track_id)
    if not tr:
        return jsonify({"ok": False, "error": "Canción no encontrada."}), 404

    db.actualizar_energia(track_id, valor, origen="manual")
    return jsonify({"ok": True})


@app.route("/api/generos/lote", methods=["POST"])
def set_genero_lote():
    """Asigna un género a varias canciones a la vez."""
    data = request.json or {}
    ids = data.get("ids", [])
    genero = (data.get("genero") or "").strip()
    fallos = []
    for tid in ids:
        tr = db.get_track(tid)
        if not tr:
            continue
        db.actualizar_genero(tid, genero)
        try:
            tags.escribir_genero(tr["ruta"], genero)
            db.refrescar_mtime(tid, tr["ruta"])
        except Exception:
            fallos.append(tr.get("titulo") or tr["ruta"])
    aviso = None
    if fallos:
        aviso = f"No se pudo escribir en el archivo de {len(fallos)} canción(es)."
    return jsonify({"ok": True, "aviso": aviso})


# ----------------------------------------------------------------------------
# BPM
# ----------------------------------------------------------------------------
@app.route("/api/bpm/calcular", methods=["POST"])
def bpm_calcular():
    if not bpm_mod.iniciar_calculo(escribir_en_archivo=True):
        return jsonify({"ok": False, "error": "Ya hay un cálculo en marcha."}), 409
    return jsonify({"ok": True})


@app.route("/api/bpm/estado")
def bpm_estado():
    return jsonify(bpm_mod.get_estado())


# ----------------------------------------------------------------------------
# Listas de reproducción
# ----------------------------------------------------------------------------
@app.route("/api/playlists")
def get_playlists():
    return jsonify(db.listar_playlists())


@app.route("/api/playlist/<int:playlist_id>")
def get_playlist(playlist_id):
    pl = db.get_playlist(playlist_id)
    if not pl:
        return jsonify({"error": "No encontrada"}), 404
    return jsonify(pl)


@app.route("/api/playlist", methods=["POST"])
def guardar_playlist():
    data = request.json or {}
    nombre = (data.get("nombre") or "").strip()
    track_ids = data.get("track_ids", [])
    if not nombre:
        return jsonify({"ok": False, "error": "Ponle un nombre a la lista."}), 400
    if not track_ids:
        return jsonify({"ok": False, "error": "La lista está vacía."}), 400
    pid = db.crear_o_reemplazar_playlist(nombre, track_ids)
    return jsonify({"ok": True, "id": pid})


@app.route("/api/playlist/<int:playlist_id>", methods=["DELETE"])
def eliminar_playlist(playlist_id):
    db.borrar_playlist(playlist_id)
    return jsonify({"ok": True})


# ----------------------------------------------------------------------------
# Exportación
# ----------------------------------------------------------------------------
@app.route("/api/playlist/<int:playlist_id>/exportar", methods=["POST"])
def exportar_playlist(playlist_id):
    pl = db.get_playlist(playlist_id)
    if not pl:
        return jsonify({"ok": False, "error": "Lista no encontrada."}), 404
    tracks = pl["tracks"]
    if not tracks:
        return jsonify({"ok": False, "error": "La lista está vacía."}), 400
    try:
        ruta_m3u = exporters.exportar_m3u8(pl["nombre"], tracks)
        ruta_nml = exporters.exportar_nml(pl["nombre"], tracks)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error al exportar: {e}"}), 500
    return jsonify({
        "ok": True,
        "rekordbox": ruta_m3u,
        "traktor": ruta_nml,
        "carpeta": exporters.EXPORT_DIR,
    })


@app.route("/exports/<path:filename>")
def descargar_export(filename):
    return send_from_directory(exporters.EXPORT_DIR, filename, as_attachment=True)


# ----------------------------------------------------------------------------
# Reproductor: sirve el audio de una canción (con soporte de búsqueda/seek)
# ----------------------------------------------------------------------------
# Tipos MIME por extensión. Los fijamos nosotros para no depender de lo que
# tenga registrado cada Windows (a veces .m4a sale como octet-stream y entonces
# el navegador se niega a reproducirlo).
MIME_AUDIO = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
    ".ogg": "audio/ogg",
}


@app.route("/api/audio/<int:track_id>")
def audio(track_id):
    tr = db.get_track(track_id)
    if not tr:
        abort(404)
    ruta = tr["ruta"]
    if not os.path.isfile(ruta):
        abort(404)
    mimetype = MIME_AUDIO.get(os.path.splitext(ruta)[1].lower())
    # conditional=True habilita las peticiones por rango (Range), necesarias
    # para poder mover la barra de reproducción dentro del tema.
    return send_file(ruta, conditional=True, mimetype=mimetype)


@app.route("/api/cover/<int:track_id>")
def cover(track_id):
    """Devuelve la portada incrustada de la canción, o 404 si no tiene."""
    tr = db.get_track(track_id)
    if not tr or not os.path.isfile(tr["ruta"]):
        abort(404)
    data, mime = cover_mod.extraer_portada(tr["ruta"])
    if not data:
        abort(404)
    resp = Response(data, mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


# ----------------------------------------------------------------------------
# Abrir la ubicación del archivo en el explorador (para el menú contextual)
# ----------------------------------------------------------------------------
@app.route("/api/track/<int:track_id>/abrir-carpeta", methods=["POST"])
def abrir_carpeta_track(track_id):
    tr = db.get_track(track_id)
    if not tr or not os.path.isfile(tr["ruta"]):
        return jsonify({"ok": False, "error": "El archivo ya no está en su ruta."}), 404
    ruta = os.path.normpath(tr["ruta"])
    try:
        if sys.platform.startswith("win"):
            # /select deja el archivo resaltado dentro de su carpeta.
            subprocess.Popen(["explorer", "/select,", ruta])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", ruta])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(ruta)])
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo abrir el explorador: {e}"}), 500
    return jsonify({"ok": True})


# ----------------------------------------------------------------------------
# Importar archivos arrastrados desde el explorador de Windows
# ----------------------------------------------------------------------------
def _destino_seguro(base, rel):
    """
    Une `base` + ruta relativa `rel` sin permitir salir de `base` (evita
    rutas con '..'). Conserva acentos y la estructura de subcarpetas.
    """
    # Descartamos separadores, '.'/'..' y cualquier segmento con ':' (letras de
    # unidad tipo 'C:' podrían saltar de disco al hacer join en Windows).
    partes = [
        p for p in re.split(r"[\\/]+", rel or "")
        if p not in ("", ".", "..") and ":" not in p
    ]
    if not partes:
        return None
    destino = os.path.normpath(os.path.join(base, *partes))
    base_abs = os.path.abspath(base)
    try:
        if os.path.commonpath([base_abs, os.path.abspath(destino)]) != base_abs:
            return None
    except ValueError:
        # Rutas en unidades distintas u otra anomalía: no es seguro.
        return None
    return destino


def _ruta_sin_colision(destino):
    """Si el archivo ya existe, añade ' (2)', ' (3)'... para no sobrescribir."""
    if not os.path.exists(destino):
        return destino
    raiz, ext = os.path.splitext(destino)
    n = 2
    while os.path.exists(f"{raiz} ({n}){ext}"):
        n += 1
    return f"{raiz} ({n}){ext}"


@app.route("/api/importar", methods=["POST"])
def importar():
    """
    Recibe archivos arrastrados desde el navegador y los COPIA dentro de la
    carpeta de música (un navegador no puede leer archivos en su sitio original
    por seguridad, así que la única forma de 'arrastrar al programa' es importar).
    Después, el frontend lanza un escaneo (incremental) para añadirlos.
    """
    carpeta = db.get_setting("carpeta_musica", "")
    if not carpeta or not os.path.isdir(carpeta):
        return jsonify({"ok": False, "error": "Primero elige tu carpeta de música (📁)."}), 400

    archivos = request.files.getlist("archivos")
    rutas_rel = request.form.getlist("rutas")  # ruta relativa opcional por archivo (carpetas arrastradas)
    if not archivos:
        return jsonify({"ok": False, "error": "No llegó ningún archivo."}), 400

    guardados = 0
    ignorados = 0
    for idx, f in enumerate(archivos):
        nombre = f.filename or ""
        rel = rutas_rel[idx] if idx < len(rutas_rel) and rutas_rel[idx] else nombre
        ext = os.path.splitext(rel)[1].lower()
        if ext not in scanner.EXTENSIONES:
            ignorados += 1
            continue
        destino = _destino_seguro(carpeta, rel)
        if not destino:
            ignorados += 1
            continue
        try:
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            f.save(_ruta_sin_colision(destino))
            guardados += 1
        except Exception as e:
            print(f"[importar] Error guardando {rel}: {e}")
            ignorados += 1

    if guardados == 0:
        return jsonify({
            "ok": False,
            "error": "No se importó nada. Solo se aceptan archivos de audio "
                     "(MP3, FLAC, WAV, AIFF, M4A, OGG).",
        }), 400

    return jsonify({"ok": True, "guardados": guardados, "ignorados": ignorados})


# ----------------------------------------------------------------------------
# Arranque
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# IA — opcional (Groq gratis por defecto, OpenRouter como extra)
# ----------------------------------------------------------------------------
@app.route("/api/ia/ajustes", methods=["GET"])
def ia_get_ajustes():
    activo = ai.proveedor_activo()
    proveedores = []
    for pid, p in ai.PROVEEDORES.items():
        cfg = ai.get_config(pid)
        key = cfg["key"]
        proveedores.append({
            "id": pid,
            "nombre": p["nombre"],
            "configurada": bool(key),
            # No devolvemos la clave completa, solo una pista.
            "clave_pista": ("…" + key[-4:]) if key else "",
            "modelo": cfg["model"],
            "modelo_defecto": p["modelo_defecto"],
            "url_clave": p["url_clave"],
            "pista_clave": p["pista_clave"],
            "modelos_sugeridos": p.get("modelos_sugeridos", []),
        })
    return jsonify({"activo": activo, "proveedores": proveedores})


@app.route("/api/ia/ajustes", methods=["POST"])
def ia_set_ajustes():
    data = request.json or {}
    # Proveedor activo (cuál usa la app).
    if data.get("proveedor") in ai.PROVEEDORES:
        db.set_setting("ia_proveedor", data["proveedor"])
    # Clave y modelo de cada proveedor (solo se sobrescribe la clave si mandan una).
    for pid, p in ai.PROVEEDORES.items():
        clave = data.get(f"{pid}_clave")
        if clave is not None and clave.strip():
            db.set_setting(p["clave_setting"], clave.strip())
        modelo = data.get(f"{pid}_modelo")
        if modelo is not None:
            db.set_setting(p["modelo_setting"], modelo.strip() or p["modelo_defecto"])
    return jsonify({"ok": True})


@app.route("/api/ia/probar", methods=["POST"])
def ia_probar():
    try:
        ok = ai.probar_conexion()
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


def _ia_guard():
    if not ai.configurada():
        return jsonify({"ok": False, "error": "Activa la IA en Ajustes — es gratis con Groq."}), 400
    return None


@app.route("/api/ia/arreglar-nombres", methods=["POST"])
def ia_arreglar_nombres():
    g = _ia_guard()
    if g:
        return g
    ids = (request.json or {}).get("ids", [])
    try:
        return jsonify({"ok": True, "propuestas": ai.arreglar_nombres(ids)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/ia/sugerir-genero", methods=["POST"])
def ia_sugerir_genero():
    g = _ia_guard()
    if g:
        return g
    ids = (request.json or {}).get("ids", [])
    try:
        return jsonify({"ok": True, "propuestas": ai.sugerir_genero(ids)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/ia/recomendar", methods=["POST"])
def ia_recomendar():
    g = _ia_guard()
    if g:
        return g
    ids = (request.json or {}).get("ids", [])
    try:
        recs = ai.recomendar(ids)
        # Adjuntamos los datos completos de cada canción recomendada.
        salida = []
        for r in recs:
            tr = db.get_track(r["id"])
            if tr:
                tr["motivo"] = r["motivo"]
                salida.append(tr)
        return jsonify({"ok": True, "tracks": salida})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/ia/armar-set", methods=["POST"])
def ia_armar_set():
    g = _ia_guard()
    if g:
        return g
    descripcion = (request.json or {}).get("descripcion", "").strip()
    if not descripcion:
        return jsonify({"ok": False, "error": "Escribe una descripción del set."}), 400
    try:
        ids = ai.armar_set(descripcion)
        tracks = [db.get_track(i) for i in ids]
        return jsonify({"ok": True, "tracks": [t for t in tracks if t]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/ia/chat", methods=["POST"])
def ia_chat():
    g = _ia_guard()
    if g:
        return g
    mensajes = (request.json or {}).get("mensajes", [])
    if not mensajes:
        return jsonify({"ok": False, "error": "Mensaje vacío."}), 400
    try:
        return jsonify({"ok": True, "respuesta": ai.chat(mensajes)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ----------------------------------------------------------------------------
# Actualizaciones
# ----------------------------------------------------------------------------
@app.route("/api/version")
def api_version():
    return jsonify({"version": VERSION})


@app.route("/api/actualizacion")
def api_actualizacion():
    """Consulta si hay una versión más nueva publicada en GitHub."""
    return jsonify(actualizaciones.comprobar())


@app.route("/api/abrir-url", methods=["POST"])
def api_abrir_url():
    """Abre un enlace en el navegador del sistema (para descargar la versión nueva)."""
    url = (request.json or {}).get("url", "")
    if not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "Enlace no válido."}), 400
    try:
        webbrowser.open(url)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


# ----------------------------------------------------------------------------
# Utilidades de arranque (multiplataforma)
# ----------------------------------------------------------------------------
def _puerto_libre(preferido=None):
    """Devuelve un puerto libre. Intenta el preferido; si está ocupado, uno al azar.
    (En macOS el 5000 suele estar ocupado por el receptor AirPlay, de ahí que no
    lo demos por sentado.)"""
    import socket
    if preferido:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", preferido))
            s.close()
            return preferido
        except OSError:
            s.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    return puerto


def _esperar_servidor(puerto, timeout=20):
    """Espera a que Flask esté aceptando conexiones antes de abrir la ventana."""
    import socket
    import time
    fin = time.time() + timeout
    while time.time() < fin:
        try:
            with socket.create_connection(("127.0.0.1", puerto), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _servir_flask(puerto):
    # threaded=True: necesario para servir el audio (streaming) mientras la
    # interfaz hace otras llamadas a la vez. use_reloader=False: no queremos el
    # recargador (lanzaría un subproceso y rompería el hilo/ventana).
    app.run(host="127.0.0.1", port=puerto, debug=False,
            use_reloader=False, threaded=True)


def _buscar_navegador_chromium():
    """Ruta a Edge o Chrome en Windows (respaldo si no hay pywebview)."""
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    localapp = os.environ.get("LOCALAPPDATA", "")
    candidatos = [
        os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pfx86, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(pfx86, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(localapp, "Google", "Chrome", "Application", "chrome.exe"),
    ]
    return next((c for c in candidatos if c and os.path.isfile(c)), None)


def _abrir_en_navegador(url):
    """
    Respaldo cuando pywebview no está disponible. En Windows abre en su propia
    ventana (modo --app de Edge/Chrome). Si no hay Edge/Chrome, o en otros
    sistemas, usa el navegador por defecto.
    """
    navegador = _buscar_navegador_chromium() if sys.platform.startswith("win") else None
    if navegador:
        perfil = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
            "MusicHub", "ventana",
        )
        try:
            subprocess.Popen([
                navegador, f"--app={url}", f"--user-data-dir={perfil}",
                "--no-first-run", "--no-default-browser-check",
            ])
            return
        except Exception:
            pass
    webbrowser.open(url)


def main():
    """
    Arranca MusicHub en su propia ventana nativa (pywebview), multiplataforma
    (Windows/macOS/Linux). Si pywebview no está instalado, cae al navegador.
    """
    db.init_db()

    # ¿Tenemos ventana nativa disponible?
    try:
        import webview  # pywebview
    except Exception:
        webview = None

    puerto = _puerto_libre(PUERTO)
    url = f"http://127.0.0.1:{puerto}"

    if webview is None:
        # Sin pywebview: Flask en el hilo principal + abrir navegador.
        threading.Timer(1.0, lambda: _abrir_en_navegador(url)).start()
        _servir_flask(puerto)
        return

    # Con pywebview: Flask en un hilo de fondo y la ventana en el principal
    # (obligatorio, sobre todo en macOS: la GUI debe ir en el hilo principal).
    global MAIN_WINDOW
    hilo = threading.Thread(target=_servir_flask, args=(puerto,), daemon=True)
    hilo.start()
    _esperar_servidor(puerto)
    try:
        MAIN_WINDOW = webview.create_window(
            "MusicHub", url,
            width=1320, height=860, min_size=(960, 640),
        )
        webview.start()
    except Exception as e:
        # Si la ventana nativa falla (p.ej. falta el runtime WebView2), no dejamos
        # al usuario sin nada: abrimos en el navegador y seguimos sirviendo.
        print(f"[MusicHub] No se pudo abrir la ventana nativa ({e}). Abro en el navegador.")
        _abrir_en_navegador(url)
        try:
            hilo.join()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
