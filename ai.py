"""
ai.py — Funciones de IA opcionales, a través de OpenRouter.

OpenRouter da acceso a muchos modelos (Claude, GPT, Gemini, Llama...) con una
sola clave, para no atarse a un proveedor. La clave y el modelo se guardan solo
en tu ordenador (base de datos local). Si no configuras la clave, estas
funciones simplemente no están disponibles y el resto del programa funciona
100% sin internet.

A la IA solo se le envía TEXTO (artista, título, género, BPM, tonalidad).
Nunca se envía el audio ni los archivos.
"""

import json
import re
import urllib.request
import urllib.error

import database as db

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Modelo por defecto (editable en Ajustes): barato y disponible en OpenRouter.
DEFAULT_MODEL = "openai/gpt-4o-mini"


def get_config():
    return {
        "key": db.get_setting("openrouter_key", "") or "",
        "model": db.get_setting("openrouter_model", DEFAULT_MODEL) or DEFAULT_MODEL,
    }


def configurada():
    return bool(get_config()["key"])


def _chat_raw(mensajes, max_tokens=1600, temperature=0.3):
    """Llama a OpenRouter con una lista completa de mensajes."""
    cfg = get_config()
    if not cfg["key"]:
        raise RuntimeError("No has configurado la clave de OpenRouter en Ajustes.")
    body = {
        "model": cfg["model"],
        "messages": mensajes,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {cfg['key']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://127.0.0.1",
            "X-Title": "MusicHub",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="ignore")[:300]
        raise RuntimeError(f"OpenRouter devolvió error {e.code}: {detalle}")
    except Exception as e:
        raise RuntimeError(f"No se pudo conectar con OpenRouter: {e}")
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise RuntimeError("Respuesta inesperada de OpenRouter.")


def _chat(system, user, max_tokens=1600):
    return _chat_raw(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
    )


def _limpiar_respuesta(texto):
    """Deja el texto listo para buscar JSON: sin razonamiento ni vallas markdown."""
    if texto is None:
        return ""
    texto = str(texto)
    # Algunos modelos "thinking" emiten su razonamiento entre <think>...</think>.
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL | re.IGNORECASE)
    texto = re.sub(r"<thinking>.*?</thinking>", "", texto, flags=re.DOTALL | re.IGNORECASE)
    texto = texto.strip()
    # Quitar vallas de código markdown (```json ... ```), estén donde estén.
    texto = re.sub(r"```(?:json)?", "", texto, flags=re.IGNORECASE)
    return texto.strip()


def _extraer_json(texto):
    """
    Extrae el primer objeto/array JSON del texto de la respuesta.

    Es tolerante: ignora texto anterior/posterior, vallas markdown, bloques de
    razonamiento, y —lo más importante— respeta las cadenas de texto, de modo
    que un corchete o llave dentro de un "motivo" no rompe el equilibrado.
    """
    limpio = _limpiar_respuesta(texto)
    candidatos = [i for i in (limpio.find("{"), limpio.find("[")) if i != -1]
    if not candidatos:
        muestra = (limpio or "(respuesta vacía)")[:200]
        raise RuntimeError(
            f"La IA no devolvió ningún dato en formato JSON. Respondió: «{muestra}»"
        )
    inicio = min(candidatos)
    apertura = limpio[inicio]
    cierre = "}" if apertura == "{" else "]"
    nivel = 0
    en_cadena = False
    escapar = False
    fin = None
    for j in range(inicio, len(limpio)):
        c = limpio[j]
        if en_cadena:
            if escapar:
                escapar = False
            elif c == "\\":
                escapar = True
            elif c == '"':
                en_cadena = False
            continue
        if c == '"':
            en_cadena = True
        elif c == apertura:
            nivel += 1
        elif c == cierre:
            nivel -= 1
            if nivel == 0:
                fin = j
                break
    if fin is None:
        raise RuntimeError(
            "La IA devolvió un JSON incompleto (seguramente la respuesta se cortó "
            "por longitud). Prueba otra vez o reduce la selección."
        )
    fragmento = limpio[inicio:fin + 1]
    try:
        return json.loads(fragmento)
    except json.JSONDecodeError as e:
        muestra = fragmento[:200]
        raise RuntimeError(
            f"La IA devolvió un JSON con un error de formato ({e.msg}). "
            f"Prueba otra vez. Fragmento: «{muestra}»"
        )


def _asegurar_lista(datos):
    """
    Normaliza la respuesta a una lista de objetos. Algunos modelos envuelven el
    array en un objeto ({"recomendaciones": [...]}), o devuelven un solo objeto.
    """
    if isinstance(datos, list):
        return datos
    if isinstance(datos, dict):
        for valor in datos.values():
            if isinstance(valor, list):
                return valor
        return [datos]
    return []


def _pedir_json_lista(system, user, max_tokens=1600):
    """
    Pide una respuesta JSON y devuelve siempre una lista de objetos. Si el
    formato falla, reintenta UNA vez recordando al modelo que responda solo JSON.
    """
    try:
        return _asegurar_lista(_extraer_json(_chat(system, user, max_tokens=max_tokens)))
    except RuntimeError:
        system2 = (
            system
            + "\n\nIMPORTANTE: Responde EXCLUSIVAMENTE con el JSON pedido. "
            "Nada de texto antes o después, sin explicaciones y sin ```."
        )
        return _asegurar_lista(_extraer_json(_chat(system2, user, max_tokens=max_tokens)))


def _resumen_track(t):
    partes = []
    if t.get("artista"):
        partes.append(f"artista='{t['artista']}'")
    if t.get("titulo"):
        partes.append(f"titulo='{t['titulo']}'")
    if t.get("album"):
        partes.append(f"album='{t['album']}'")
    if t.get("genero"):
        partes.append(f"genero='{t['genero']}'")
    if t.get("bpm") is not None:
        partes.append(f"bpm={t['bpm']}")
    if t.get("tonalidad"):
        partes.append(f"key={t['tonalidad']}")
    return ", ".join(partes)


# ---------------------------------------------------------------------------
def probar_conexion():
    """Comprueba que la clave y el modelo funcionan."""
    r = _chat("Responde solo con la palabra OK.", "Di OK.", max_tokens=10)
    return "ok" in r.lower()


def arreglar_nombres(ids):
    """
    Propone artista/título limpios para las canciones indicadas.
    Devuelve una lista de propuestas (el usuario decide si aplicarlas).
    """
    tracks = [db.get_track(i) for i in ids]
    tracks = [t for t in tracks if t]
    if not tracks:
        return []
    lineas = [
        f"{t['id']}: artista='{t.get('artista') or ''}' | titulo='{t.get('titulo') or ''}'"
        for t in tracks
    ]
    system = (
        "Eres un experto catalogando música electrónica. Te doy canciones con "
        "artista y título posiblemente mal escritos o con basura (por ejemplo "
        "'(Official Video)', 'HD', '320kbps', guiones de más, mayúsculas raras, "
        "el artista metido en el título, etc.). Devuelve SOLO un array JSON con "
        "objetos {\"id\": <id>, \"artista\": \"...\", \"titulo\": \"...\"} con la "
        "versión corregida y limpia. Mantén el idioma original. Si algo ya está "
        "bien, repítelo igual. No inventes datos que no puedas deducir."
    )
    user = "Canciones:\n" + "\n".join(lineas)
    datos = _pedir_json_lista(system, user)
    por_id = {t["id"]: t for t in tracks}
    propuestas = []
    for d in datos:
        if not isinstance(d, dict):
            continue
        tid = d.get("id")
        if tid in por_id:
            t = por_id[tid]
            propuestas.append({
                "id": tid,
                "artista_actual": t.get("artista") or "",
                "titulo_actual": t.get("titulo") or "",
                "artista": (d.get("artista") or "").strip(),
                "titulo": (d.get("titulo") or "").strip(),
            })
    return propuestas


def sugerir_genero(ids):
    """Propone un género para cada canción, coherente con la colección."""
    tracks = [db.get_track(i) for i in ids]
    tracks = [t for t in tracks if t]
    if not tracks:
        return []
    existentes = db.generos_existentes()
    lineas = [f"{t['id']}: {_resumen_track(t)}" for t in tracks]
    system = (
        "Eres DJ y experto en subgéneros de música electrónica. Propón el "
        "género más adecuado para cada canción. Prioriza reutilizar los géneros "
        "que ya usa esta colección si encajan. Devuelve SOLO un array JSON de "
        "objetos {\"id\": <id>, \"genero\": \"...\"}."
    )
    user = (
        f"Géneros ya usados en la colección: {', '.join(existentes) or '(ninguno)'}\n\n"
        "Canciones:\n" + "\n".join(lineas)
    )
    datos = _pedir_json_lista(system, user)
    por_id = {t["id"]: t for t in tracks}
    propuestas = []
    for d in datos:
        if not isinstance(d, dict):
            continue
        tid = d.get("id")
        if tid in por_id and d.get("genero"):
            propuestas.append({
                "id": tid,
                "genero_actual": por_id[tid].get("genero") or "",
                "genero": d["genero"].strip(),
            })
    return propuestas


def _camelot_compatibles(key):
    """Claves Camelot que mezclan bien con `key` (misma, ±1 número, cambio de letra)."""
    m = re.match(r"^(\d{1,2})([AB])$", (key or "").strip())
    if not m:
        return set()
    n = int(m.group(1))
    letra = m.group(2)
    otra = "B" if letra == "A" else "A"
    return {
        f"{n}{letra}",
        f"{(n % 12) + 1}{letra}",
        f"{((n - 2) % 12) + 1}{letra}",
        f"{n}{otra}",
    }


def _recomendar_local(semilla, candidatos, limite):
    """
    Recomendación SIN IA: puntúa candidatos por cercanía de BPM, compatibilidad
    de tonalidad (Camelot) y coincidencia de género. Sirve de red de seguridad
    si la IA falla, para que el botón siempre devuelva algo útil.
    """
    compat = set()
    for t in semilla:
        compat |= _camelot_compatibles(t.get("tonalidad"))
    bpms = [t["bpm"] for t in semilla if t.get("bpm")]
    centro = sum(bpms) / len(bpms) if bpms else None
    generos = {(t.get("genero") or "").lower() for t in semilla if t.get("genero")}

    puntuados = []
    for t in candidatos:
        score = 0
        motivos = []
        if centro and t.get("bpm"):
            d = abs(t["bpm"] - centro)
            if d <= 3:
                score += 3
                motivos.append("BPM muy cercano")
            elif d <= 6:
                score += 2
                motivos.append("BPM cercano")
            elif d <= 10:
                score += 1
        if t.get("tonalidad") and t["tonalidad"] in compat:
            score += 3
            motivos.append(f"tonalidad compatible ({t['tonalidad']})")
        if generos and (t.get("genero") or "").lower() in generos:
            score += 1
            motivos.append("mismo género")
        if score > 0:
            puntuados.append((score, {"id": t["id"], "motivo": ", ".join(motivos) or "compatible"}))

    puntuados.sort(key=lambda x: -x[0])
    return [p[1] for p in puntuados[:limite]]


def recomendar(semilla_ids, limite=15):
    """
    Recomienda temas de la colección compatibles con los de partida (semilla),
    priorizando BPM y tonalidad cercanos. Devuelve ids ordenados con un motivo.

    Intenta con la IA; si la IA falla o no devuelve nada aprovechable, cae a una
    recomendación local (misma lógica de BPM/tonalidad/género) para no dejar al
    usuario sin resultado.
    """
    semilla = [db.get_track(i) for i in semilla_ids]
    semilla = [t for t in semilla if t]
    if not semilla:
        return []
    ids_semilla = {t["id"] for t in semilla}
    todos = [t for t in db.listar_tracks() if t["id"] not in ids_semilla]

    # Pre-filtramos candidatos por cercanía de BPM (±8) si hay BPM de referencia.
    bpms = [t["bpm"] for t in semilla if t.get("bpm")]
    if bpms:
        centro = sum(bpms) / len(bpms)
        candidatos = [t for t in todos if t.get("bpm") and abs(t["bpm"] - centro) <= 8]
        if len(candidatos) < 10:
            candidatos = todos
    else:
        candidatos = todos
    candidatos = candidatos[:120]  # límite de tokens
    validos = {t["id"] for t in candidatos}

    system = (
        "Eres un DJ preparando un set. Te doy unas canciones de referencia y una "
        "lista de candidatas de la misma biblioteca. Elige las que mejor encajan "
        "para seguir mezclando, teniendo en cuenta género, BPM cercano y "
        "tonalidad compatible (rueda Camelot: misma clave, o ±1 número, o cambio "
        "de letra manteniendo el número). Devuelve SOLO un array JSON de objetos "
        "{\"id\": <id>, \"motivo\": \"...\"} ordenados de mejor a peor, máximo "
        f"{limite}. El \"motivo\" debe ser MUY breve (máx. 8 palabras) y sin "
        "comillas dobles ni corchetes dentro."
    )
    user = (
        "Referencia:\n" + "\n".join(f"{t['id']}: {_resumen_track(t)}" for t in semilla) +
        "\n\nCandidatas:\n" + "\n".join(f"{t['id']}: {_resumen_track(t)}" for t in candidatos)
    )
    try:
        datos = _pedir_json_lista(system, user, max_tokens=2200)
        salida = [
            {"id": d["id"], "motivo": (d.get("motivo") or "").strip()}
            for d in datos
            if isinstance(d, dict) and d.get("id") in validos
        ][:limite]
        if salida:
            return salida
    except RuntimeError:
        pass  # la IA no dio un JSON aprovechable: usamos el cálculo local.

    return _recomendar_local(semilla, candidatos, limite)


def _contexto_biblioteca(max_tracks=250):
    """Resumen compacto de la colección para dar contexto al chat."""
    tracks = db.listar_tracks()
    if not tracks:
        return "La biblioteca está vacía (aún no se ha escaneado música)."
    generos = {}
    bpms = []
    for t in tracks:
        if t.get("genero"):
            generos[t["genero"]] = generos.get(t["genero"], 0) + 1
        if t.get("bpm"):
            bpms.append(t["bpm"])
    resumen = [f"Total de canciones: {len(tracks)}."]
    if generos:
        gg = ", ".join(f"{g} ({n})" for g, n in sorted(generos.items(), key=lambda x: -x[1]))
        resumen.append(f"Géneros: {gg}.")
    if bpms:
        resumen.append(f"BPM entre {min(bpms):.0f} y {max(bpms):.0f}.")
    resumen.append(
        f"\nLista de canciones (usa estos id para proponer sets){' [muestra parcial]' if len(tracks) > max_tracks else ''}:"
    )
    for t in tracks[:max_tracks]:
        resumen.append(f"{t['id']}: {_resumen_track(t)}")
    return "\n".join(resumen)


def chat(historial):
    """
    Chat conversacional con contexto de la colección. `historial` es una lista
    de {role: 'user'|'assistant', content: str}. Devuelve el texto de respuesta.

    Convención de acción: si el modelo propone un set concreto, termina su
    mensaje con una línea 'SET: [id, id, ...]' que la interfaz convierte en un
    botón para cargar esos temas en el panel de preparación.
    """
    system = (
        "Eres el asistente de MusicHub, un programa de escritorio para que un DJ "
        "organice su colección de música electrónica y prepare sets. Hablas en "
        "español, de forma cercana y concisa, como otro DJ. Conoces la biblioteca "
        "del usuario (te la paso abajo). Ayudas a: encontrar temas, planificar "
        "sets (por género, BPM y tonalidad Camelot para mezcla armónica), sugerir "
        "géneros, y dar consejo de mezcla. No inventes canciones que no estén en "
        "la biblioteca.\n\n"
        "Cuando propongas un set o una selección concreta de temas, añade al FINAL "
        "del mensaje una línea con este formato exacto (solo los id, de la lista):\n"
        "SET: [12, 45, 7]\n"
        "para que el usuario pueda cargarlos con un clic. Si no propones temas "
        "concretos, no incluyas esa línea.\n\n"
        "=== BIBLIOTECA DEL USUARIO ===\n" + _contexto_biblioteca()
    )
    mensajes = [{"role": "system", "content": system}]
    # Limitamos el historial a los últimos intercambios para no disparar tokens.
    for m in historial[-12:]:
        rol = "assistant" if m.get("role") == "assistant" else "user"
        mensajes.append({"role": rol, "content": str(m.get("content", ""))})
    return _chat_raw(mensajes, max_tokens=1200, temperature=0.5)


def armar_set(descripcion, limite=20):
    """
    Arma un set candidato a partir de una descripción en lenguaje natural,
    eligiendo temas de la biblioteca.
    """
    todos = db.listar_tracks()
    if not todos:
        return []
    # Enviamos un resumen compacto de la biblioteca (limitado por tokens).
    muestra = todos[:400]
    system = (
        "Eres un DJ que arma sets a partir de una descripción. Elige de la "
        "biblioteca las canciones que encajan con lo pedido (género, ambiente, "
        "rango de BPM, tonalidad) y ordénalas en un orden de reproducción "
        "coherente para una sesión. Devuelve SOLO un array JSON de objetos "
        f"{{\"id\": <id>}} en orden, máximo {limite}. Usa solo ids de la lista."
    )
    user = (
        f"Descripción del set: {descripcion}\n\n"
        "Biblioteca:\n" + "\n".join(f"{t['id']}: {_resumen_track(t)}" for t in muestra)
    )
    datos = _pedir_json_lista(system, user)
    validos = {t["id"] for t in muestra}
    orden = []
    for d in datos:
        if not isinstance(d, dict):
            continue
        tid = d.get("id")
        if tid in validos and tid not in orden:
            orden.append(tid)
    return orden[:limite]
