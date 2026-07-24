// =====================================================================
//  MusicHub — lógica de la interfaz (JS vanilla, sin librerías externas)
// =====================================================================

let TRACKS = [];                 // toda la biblioteca
let PORID = new Map();           // id -> track
let GENEROS = [];                // géneros existentes
let LISTAS = [];                 // playlists guardadas
let RAIZ = "";                   // carpeta raíz de la música

let fuente = { tipo: "coleccion", nombre: "Toda la colección" };
let orden = { campo: "artista", asc: true };
let seleccion = new Set();       // ids marcados en el navegador
let prep = [];                   // canciones del set en preparación
let prepId = null;               // id de la lista guardada que estamos editando
const reproEl = { actual: null };

const carpetasExpandidas = new Set();  // rutas de carpetas abiertas en el árbol (persiste entre renders)
let carpetasConHijos = new Set();      // qué rutas tienen subcarpetas (para saber si mostrar flechita)

// ---------- utilidades ----------
async function api(url, opciones) {
    const r = await fetch(url, opciones);
    let data = null;
    try { data = await r.json(); } catch (e) {}
    if (!r.ok) throw new Error((data && data.error) || ("Error " + r.status));
    return data;
}
function post(url, cuerpo) {
    return api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo || {}) });
}
function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function fmtDur(seg) {
    if (!seg) return "0:00";
    const m = Math.floor(seg / 60), s = Math.floor(seg % 60);
    return m + ":" + String(s).padStart(2, "0");
}
function toast(msg, ms = 4500) {
    const t = document.getElementById("toast");
    t.textContent = msg;
    t.classList.remove("oculto");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.add("oculto"), ms);
}
function slot(id, tam) {
    return `<div class="cover-slot cover-${tam}"><img loading="lazy" src="/api/cover/${id}"></div>`;
}
// color de la pill de tonalidad (rueda Camelot: 12 tonos, mayor/menor con distinto brillo)
function colorCamelot(key) {
    const m = /^(\d{1,2})([AB])$/.exec(key || "");
    if (!m) return "";
    const num = parseInt(m[1], 10);
    const letra = m[2];
    const hue = ((num - 1) * 30) % 360;
    const luz = letra === "A" ? 30 : 38;
    return `background:hsl(${hue} 62% ${luz}%);color:hsl(${hue} 85% 88%);`;
}
// color de la pill de energía (1-10): verde -> amarillo -> naranja -> rojo
function colorEnergia(valor) {
    if (valor == null) return "";
    const t = Math.max(0, Math.min(1, (valor - 1) / 9));
    const hue = 140 - t * 140;
    return `background:hsl(${hue} 65% 26%);color:hsl(${hue} 85% 85%);`;
}
// Ocultar imágenes de portada que no cargan (sin portada) -> se ve la nota musical.
document.addEventListener("error", e => {
    const el = e.target;
    if (el.tagName === "IMG" && el.closest(".cover-slot")) el.style.visibility = "hidden";
}, true);

// =====================================================================
//  CARGA INICIAL
// =====================================================================
async function cargarTodo() {
    const c = await api("/api/carpeta");
    RAIZ = c.carpeta || "";
    TRACKS = await api("/api/tracks");
    PORID = new Map(TRACKS.map(t => [t.id, t]));
    GENEROS = await api("/api/generos");
    LISTAS = await api("/api/playlists");
    document.getElementById("lista-generos").innerHTML = GENEROS.map(g => `<option value="${esc(g)}">`).join("");
    renderSidebar();
    renderNavegador();
    renderPrep();
    if (!c.carpeta && TRACKS.length === 0) {
        toast("Bienvenido. Pulsa «Carpeta» arriba para elegir tu música y luego «Escanear».", 8000);
    }
}

// =====================================================================
//  SIDEBAR (fuentes)
// =====================================================================
function renderSidebar() {
    const sinGenero = TRACKS.filter(t => !t.genero).length;
    const sinBpm = TRACKS.filter(t => t.bpm == null).length;
    const fijas = [
        { tipo: "coleccion", ico: "", nombre: "Toda la colección", cont: TRACKS.length },
        { tipo: "sin-genero", ico: "", nombre: "Sin género", cont: sinGenero },
        { tipo: "sin-bpm", ico: "", nombre: "Sin BPM", cont: sinBpm },
    ];
    document.getElementById("fuentes-fijas").innerHTML = fijas.map(f => filaFuente(f)).join("");

    // carpetas (árbol): cada nodo cuenta sus canciones y las de sus subcarpetas
    renderCarpetas();

    // géneros con recuento
    const conteo = {};
    TRACKS.forEach(t => { if (t.genero) conteo[t.genero] = (conteo[t.genero] || 0) + 1; });
    const gens = Object.keys(conteo).sort((a, b) => a.localeCompare(b));
    const ulG = document.getElementById("fuentes-generos");
    ulG.innerHTML = gens.length
        ? gens.map(g => filaFuente({ tipo: "genero", valor: g, ico: "", nombre: g, cont: conteo[g] })).join("")
        : `<li class="vacio-lista">Aún no hay géneros</li>`;

    // listas guardadas
    const ulL = document.getElementById("fuentes-listas");
    ulL.innerHTML = LISTAS.length
        ? LISTAS.map(p => filaFuente({ tipo: "playlist", valor: p.id, ico: "", nombre: p.nombre, cont: p.num, borrable: true })).join("")
        : `<li class="vacio-lista">Aún no hay listas</li>`;
}
// normaliza una subcarpeta a separador "/" y sin barras sobrantes
function normSub(s) {
    return (s || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
}
function renderCarpetas() {
    const grupo = document.getElementById("grupo-carpetas");
    const ul = document.getElementById("fuentes-carpetas");

    const nodos = new Map();   // ruta relativa -> nº de canciones (incluye subcarpetas)
    const hijos = new Map();   // ruta padre ("" = raíz del árbol) -> Set de rutas hijas directas
    let enRaiz = 0;
    TRACKS.forEach(t => {
        const s = normSub(t.subcarpeta);
        if (!s) { enRaiz++; return; }
        const segs = s.split("/");
        for (let i = 1; i <= segs.length; i++) {
            const pref = segs.slice(0, i).join("/");
            nodos.set(pref, (nodos.get(pref) || 0) + 1);
            const padre = i === 1 ? "" : segs.slice(0, i - 1).join("/");
            if (!hijos.has(padre)) hijos.set(padre, new Set());
            hijos.get(padre).add(pref);
        }
    });

    // Si no hay subcarpetas reales, ocultamos el grupo (biblioteca plana).
    if (nodos.size === 0) { grupo.classList.add("oculto"); ul.innerHTML = ""; return; }
    grupo.classList.remove("oculto");
    carpetasConHijos = new Set(hijos.keys());

    let html = "";
    if (enRaiz > 0) {
        const act = fuente.tipo === "carpeta" && fuente.valor === "" ? "activa" : "";
        html += `<li class="fila-carpeta ${act}" data-tipo="carpeta" data-valor="" style="--nivel:0">
            <span class="carpeta-toggle"></span>
            <span class="ico"></span><span class="txt">(en la carpeta raíz)</span><span class="cont">${enRaiz}</span></li>`;
    }

    // Recorre el árbol en profundidad, pero solo "abre" (pinta) los hijos de
    // las carpetas que el usuario tiene expandidas — así el árbol empieza
    // plegado y organizado en vez de mostrar cientos de subcarpetas de golpe.
    const pintarNivel = (padre, nivel) => {
        const hijosDe = [...(hijos.get(padre) || [])].sort((a, b) => a.localeCompare(b, "es"));
        for (const r of hijosDe) {
            const etiqueta = r.split("/").pop();
            const tieneHijos = hijos.has(r);
            const expandida = carpetasExpandidas.has(r);
            const act = fuente.tipo === "carpeta" && fuente.valor === r ? "activa" : "";
            const toggle = tieneHijos
                ? `<span class="carpeta-toggle" data-toggle="${esc(r)}">${expandida ? "▾" : "▸"}</span>`
                : `<span class="carpeta-toggle"></span>`;
            html += `<li class="fila-carpeta ${act}" data-tipo="carpeta" data-valor="${esc(r)}" style="--nivel:${nivel}" title="${esc(r)}">
                ${toggle}<span class="txt">${esc(etiqueta)}</span><span class="cont">${nodos.get(r)}</span></li>`;
            if (tieneHijos && expandida) pintarNivel(r, nivel + 1);
        }
    };
    pintarNivel("", 0);

    ul.innerHTML = html;
}
function filaFuente(f) {
    const act = (fuente.tipo === f.tipo && (f.valor === undefined || String(fuente.valor) === String(f.valor))) ? "activa" : "";
    const borrar = f.borrable ? `<span class="fuente-borrar" data-borrar="${f.valor}" title="Borrar lista">✕</span>` : "";
    return `<li class="${act}" data-tipo="${f.tipo}" data-valor="${esc(f.valor ?? "")}">
        <span class="txt">${esc(f.nombre)}</span>
        <span class="cont">${f.cont}</span>${borrar}
    </li>`;
}

document.querySelector(".sidebar").addEventListener("click", async e => {
    // Flechita ▸/▾ de una carpeta: solo pliega/despliega, no cambia la vista.
    const toggle = e.target.closest(".carpeta-toggle");
    if (toggle && toggle.dataset.toggle !== undefined) {
        e.stopPropagation();
        const ruta = toggle.dataset.toggle;
        if (carpetasExpandidas.has(ruta)) carpetasExpandidas.delete(ruta); else carpetasExpandidas.add(ruta);
        renderCarpetas();
        return;
    }

    const borrar = e.target.closest(".fuente-borrar");
    if (borrar) {
        e.stopPropagation();
        const id = +borrar.dataset.borrar;
        const lista = LISTAS.find(l => l.id === id);
        if (!confirm(`¿Borrar la lista "${lista ? lista.nombre : ""}"? (No borra ninguna canción.)`)) return;
        await fetch(`/api/playlist/${id}`, { method: "DELETE" });
        if (fuente.tipo === "playlist" && String(fuente.valor) === String(id)) fuente = { tipo: "coleccion", nombre: "Toda la colección" };
        LISTAS = await api("/api/playlists");
        renderSidebar(); renderNavegador();
        return;
    }
    const li = e.target.closest("li[data-tipo]");
    if (!li) return;
    // Clic en el resto de la fila de una carpeta: además de seleccionarla,
    // la expande/pliega si tiene subcarpetas (un solo clic para explorar).
    if (li.dataset.tipo === "carpeta" && carpetasConHijos.has(li.dataset.valor)) {
        const ruta = li.dataset.valor;
        if (carpetasExpandidas.has(ruta)) carpetasExpandidas.delete(ruta); else carpetasExpandidas.add(ruta);
    }
    await seleccionarFuente(li.dataset.tipo, li.dataset.valor);
});

async function seleccionarFuente(tipo, valor) {
    seleccion.clear();
    if (tipo === "playlist") {
        const pl = await api(`/api/playlist/${valor}`);
        fuente = { tipo, valor: +valor, nombre: pl.nombre, tracks: pl.tracks };
    } else if (tipo === "genero") {
        fuente = { tipo, valor, nombre: valor };
    } else if (tipo === "carpeta") {
        const nombre = valor === "" ? " En la carpeta raíz" : " " + valor.replace(/\//g, " › ");
        fuente = { tipo, valor, nombre };
    } else if (tipo === "sin-genero") {
        fuente = { tipo, nombre: "Sin género" };
    } else if (tipo === "sin-bpm") {
        fuente = { tipo, nombre: "Sin BPM" };
    } else {
        fuente = { tipo: "coleccion", nombre: "Toda la colección" };
    }
    renderSidebar();
    renderNavegador();
}

// =====================================================================
//  NAVEGADOR (centro)
// =====================================================================
function tracksBase() {
    if (fuente.tipo === "playlist") return fuente.tracks || [];
    if (fuente.tipo === "genero") return TRACKS.filter(t => t.genero === fuente.valor);
    if (fuente.tipo === "carpeta") {
        const node = fuente.valor;   // "" = solo las de la raíz
        return TRACKS.filter(t => {
            const s = normSub(t.subcarpeta);
            return node === "" ? s === "" : (s === node || s.startsWith(node + "/"));
        });
    }
    if (fuente.tipo === "sin-genero") return TRACKS.filter(t => !t.genero);
    if (fuente.tipo === "sin-bpm") return TRACKS.filter(t => t.bpm == null);
    return TRACKS;
}
function tracksDeVista() {
    const q = document.getElementById("buscar").value.toLowerCase().trim();
    const bmin = parseFloat(document.getElementById("bpm-min").value);
    const bmax = parseFloat(document.getElementById("bpm-max").value);
    let lista = tracksBase();
    if (q) lista = lista.filter(t => ((t.artista || "") + " " + (t.titulo || "") + " " + (t.album || "")).toLowerCase().includes(q));
    if (!isNaN(bmin)) lista = lista.filter(t => t.bpm != null && t.bpm >= bmin);
    if (!isNaN(bmax)) lista = lista.filter(t => t.bpm != null && t.bpm <= bmax);
    // El orden manual de las playlists se respeta salvo que el usuario ordene por columna.
    if (!(fuente.tipo === "playlist" && orden.campo === "_playlist")) {
        const { campo, asc } = orden;
        lista = [...lista].sort((a, b) => {
            let va = a[campo], vb = b[campo];
            if (campo === "bpm" || campo === "duracion" || campo === "energia") { va = va || 0; vb = vb || 0; return asc ? va - vb : vb - va; }
            va = (va || "").toString().toLowerCase(); vb = (vb || "").toString().toLowerCase();
            return asc ? va.localeCompare(vb) : vb.localeCompare(va);
        });
    }
    return lista;
}

function renderStats(lista) {
    const cont = document.getElementById("fuente-info");
    if (!lista.length) { cont.innerHTML = ""; return; }
    const artistas = new Set(lista.map(t => t.artista).filter(Boolean)).size;
    const segTotal = lista.reduce((s, t) => s + (t.duracion || 0), 0);
    const horas = Math.floor(segTotal / 3600);
    const minutos = Math.round((segTotal % 3600) / 60);
    const bpms = lista.map(t => t.bpm).filter(v => v != null);
    const energias = lista.map(t => t.energia).filter(v => v != null);

    const stats = [
        { label: "Tracks", valor: lista.length },
        { label: "Artistas", valor: artistas },
        { label: "Horas", valor: horas > 0 ? `${horas}h ${minutos}m` : `${minutos}m` },
    ];
    if (bpms.length) stats.push({ label: "BPM", valor: `${Math.round(Math.min(...bpms))}–${Math.round(Math.max(...bpms))}` });
    if (energias.length) stats.push({ label: "Energy", valor: `${Math.min(...energias)}–${Math.max(...energias)}` });

    cont.innerHTML = stats.map((s, i) =>
        (i > 0 ? `<span class="sep">·</span>` : "") +
        `<span class="stat">${s.label} <b>${s.valor}</b></span>`
    ).join("");
}

function renderNavegador() {
    document.getElementById("fuente-nombre").textContent = fuente.nombre;
    const lista = tracksDeVista();
    renderStats(lista);
    document.getElementById("btn-cargar-todo").classList.toggle("oculto", fuente.tipo !== "playlist");

    const tb = document.getElementById("cuerpo-tracks");
    tb.innerHTML = lista.map(t => {
        const gen = t.genero ? esc(t.genero) : `(sin género)`;
        let bpm = `<span class="sin-dato">—</span>`;
        if (t.bpm != null) {
            const cls = t.bpm_origen === "calculado" ? "calc" : "";
            const tag = t.bpm_origen === "calculado" ? ` <span class="mini-tag">calc</span>` : "";
            bpm = `<span class="pill-bpm ${cls}">${t.bpm}</span>${tag}`;
        }
        const key = t.tonalidad
            ? `<span class="pill-key" style="${colorCamelot(t.tonalidad)}">${esc(t.tonalidad)}</span>`
            : `<span class="sin-dato">—</span>`;
        const energia = t.energia != null
            ? `<span class="pill-energy" style="${colorEnergia(t.energia)}">${t.energia}</span>`
            : `<span class="sin-dato">—</span>`;
        const son = reproEl.actual === t.id;
        return `<tr data-id="${t.id}" draggable="true" class="${son ? "sonando-fila" : ""}">
            <td class="c-check"><input type="checkbox" class="chk" ${seleccion.has(t.id) ? "checked" : ""}></td>
            <td class="c-cover">${slot(t.id, 32)}</td>
            <td class="c-play"><button class="btn-icono btn-play ${son ? "sonando" : ""}" title="Escuchar">▶</button></td>
            <td class="td-artista celda-edit" data-campo="artista">${esc(t.artista)}</td>
            <td class="td-titulo celda-edit" data-campo="titulo">${esc(t.titulo)}</td>
            <td class="celda-genero ${t.genero ? "" : "vacio"}">${gen}</td>
            <td class="c-bpm">${bpm}</td>
            <td class="c-key">${key}</td>
            <td class="c-energy celda-energia">${energia}</td>
            <td class="c-dur td-dur">${fmtDur(t.duracion)}</td>
            <td class="c-add"><button class="btn-icono btn-add" title="Añadir al set">＋</button></td>
        </tr>`;
    }).join("");

    const vacio = document.getElementById("vacio-nav");
    if (lista.length === 0) {
        vacio.classList.remove("oculto");
        if (TRACKS.length === 0) {
            vacio.innerHTML = `<img class="vacio-logo" src="/static/logo.png" alt="MusicHub">
                <div>Tu biblioteca está vacía. Elige tu carpeta de música y pulsa «Escanear».<br>
                También puedes arrastrar aquí tus archivos o carpetas de música.</div>`;
        } else {
            vacio.textContent = "No hay canciones que coincidan con esta vista.";
        }
    } else vacio.classList.add("oculto");

    actualizarLoteUI();
}

// buscar y filtrar
document.getElementById("buscar").addEventListener("input", renderNavegador);
document.getElementById("bpm-min").addEventListener("input", renderNavegador);
document.getElementById("bpm-max").addEventListener("input", renderNavegador);
document.querySelectorAll("#tabla-tracks thead th[data-orden]").forEach(th => {
    th.onclick = () => {
        const campo = th.dataset.orden;
        if (orden.campo === campo) orden.asc = !orden.asc; else orden = { campo, asc: true };
        renderNavegador();
    };
});

// clics dentro del navegador (delegación): play, add, editar género
document.getElementById("cuerpo-tracks").addEventListener("click", e => {
    const tr = e.target.closest("tr");
    if (!tr) return;
    const id = +tr.dataset.id;

    if (e.target.closest(".btn-play")) { reproducir(PORID.get(id)); return; }
    if (e.target.closest(".btn-add")) { anadirAlSet([id]); return; }

    const celdaGen = e.target.closest(".celda-genero");
    if (celdaGen && !celdaGen.querySelector("input")) { editarGenero(celdaGen, id); return; }

    const celdaEn = e.target.closest(".celda-energia");
    if (celdaEn && !celdaEn.querySelector("input")) { editarEnergia(celdaEn, id); return; }

    const celdaEd = e.target.closest(".celda-edit");
    if (celdaEd && !celdaEd.querySelector("input")) editarCampo(celdaEd, id, celdaEd.dataset.campo);
});

function editarEnergia(celda, id) {
    const track = PORID.get(id);
    const actual = track.energia != null ? track.energia : "";
    celda.innerHTML = `<input type="number" min="1" max="10" step="1" value="${actual}">`;
    const inp = celda.querySelector("input");
    inp.focus(); inp.select();
    let guardado = false;
    const guardar = async () => {
        if (guardado) return; guardado = true;
        const valor = parseInt(inp.value, 10);
        if (!isNaN(valor) && valor >= 1 && valor <= 10 && valor !== track.energia) {
            try {
                await post(`/api/track/${id}/energia`, { valor });
                track.energia = valor;
                track.energia_origen = "manual";
            } catch (err) { toast("" + err.message); }
        }
        renderNavegador();
    };
    inp.addEventListener("keydown", ev => {
        if (ev.key === "Enter") inp.blur();
        if (ev.key === "Escape") { guardado = true; renderNavegador(); }
    });
    inp.addEventListener("blur", guardar);
}

function editarCampo(celda, id, campo) {
    const track = PORID.get(id);
    const actual = track[campo] || "";
    celda.innerHTML = `<input type="text" value="${esc(actual)}">`;
    const inp = celda.querySelector("input");
    inp.focus(); inp.select();
    let guardado = false;
    const guardar = async () => {
        if (guardado) return; guardado = true;
        const valor = inp.value.trim();
        if (valor !== actual) {
            try {
                const r = await post(`/api/track/${id}/campo`, { campo, valor });
                track[campo] = valor;
                if (r.aviso) toast("" + r.aviso);
            } catch (err) { toast("" + err.message); }
        }
        renderNavegador();
    };
    inp.addEventListener("keydown", ev => {
        if (ev.key === "Enter") inp.blur();
        if (ev.key === "Escape") { guardado = true; renderNavegador(); }
    });
    inp.addEventListener("blur", guardar);
}

function editarGenero(celda, id) {
    const track = PORID.get(id);
    celda.innerHTML = `<input type="text" list="lista-generos" value="${esc(track.genero || "")}">`;
    const inp = celda.querySelector("input");
    inp.focus(); inp.select();
    let guardado = false;
    const guardar = async () => {
        if (guardado) return; guardado = true;
        const valor = inp.value.trim();
        try {
            const r = await post(`/api/track/${id}/genero`, { genero: valor });
            track.genero = valor;
            if (r.aviso) toast("" + r.aviso);
            GENEROS = await api("/api/generos");
            document.getElementById("lista-generos").innerHTML = GENEROS.map(g => `<option value="${esc(g)}">`).join("");
            renderSidebar();
        } catch (err) { toast("" + err.message); }
        renderNavegador();
    };
    inp.addEventListener("keydown", ev => {
        if (ev.key === "Enter") inp.blur();
        if (ev.key === "Escape") { guardado = true; renderNavegador(); }
    });
    inp.addEventListener("blur", guardar);
}

// selección (checkboxes)
document.getElementById("cuerpo-tracks").addEventListener("change", e => {
    if (!e.target.classList.contains("chk")) return;
    const id = +e.target.closest("tr").dataset.id;
    if (e.target.checked) seleccion.add(id); else seleccion.delete(id);
    actualizarLoteUI();
});
document.getElementById("check-todos").addEventListener("change", e => {
    const vis = tracksDeVista();
    if (e.target.checked) vis.forEach(t => seleccion.add(t.id)); else vis.forEach(t => seleccion.delete(t.id));
    renderNavegador();
});
function actualizarLoteUI() {
    document.getElementById("lote-acciones").classList.toggle("oculto", seleccion.size === 0);
    const n = seleccion.size;
    document.getElementById("btn-add-seleccion").textContent = `Añadir ${n} al set →`;
}

// género en lote
document.getElementById("btn-aplicar-lote").onclick = async () => {
    const genero = document.getElementById("genero-lote").value.trim();
    const ids = [...seleccion];
    if (!ids.length) return;
    try {
        const r = await post("/api/generos/lote", { ids, genero });
        ids.forEach(id => { const t = PORID.get(id); if (t) t.genero = genero; });
        toast(r.aviso ? "" + r.aviso : `Género aplicado a ${ids.length} canciones.`);
        GENEROS = await api("/api/generos");
        renderSidebar(); renderNavegador();
    } catch (e) { toast("" + e.message); }
};
document.getElementById("btn-add-seleccion").onclick = () => anadirAlSet([...seleccion]);
document.getElementById("btn-cargar-todo").onclick = () => {
    prep = (fuente.tracks || []).slice();
    prepId = fuente.valor;
    document.getElementById("nombre-set").value = fuente.nombre;
    renderPrep();
    toast(`Lista "${fuente.nombre}" cargada en el set. Edítala y vuelve a guardar.`);
};

// arrastrar filas hacia el panel de preparación
document.getElementById("cuerpo-tracks").addEventListener("dragstart", e => {
    const tr = e.target.closest("tr");
    if (!tr) return;
    const id = +tr.dataset.id;
    const ids = (seleccion.has(id) && seleccion.size > 1) ? [...seleccion] : [id];
    e.dataTransfer.setData("text/plain", JSON.stringify(ids));
    e.dataTransfer.effectAllowed = "copy";
});

// =====================================================================
//  PANEL DE PREPARACIÓN (set)
// =====================================================================
function anadirAlSet(ids) {
    let nuevos = 0;
    ids.forEach(id => {
        if (!prep.some(t => t.id === id)) { prep.push(PORID.get(id)); nuevos++; }
    });
    renderPrep();
    if (nuevos) toast(`Añadida${nuevos > 1 ? "s " + nuevos : ""} al set.`, 1800);
    else toast("Ya estaba en el set.", 1500);
}

function renderPrep() {
    const ol = document.getElementById("prep-lista");
    document.getElementById("prep-vacio").classList.toggle("oculto", prep.length > 0);
    ol.innerHTML = prep.map((t, i) => {
        const son = reproEl.actual === t.id;
        const keyPill = t.tonalidad ? ` <span class="mini-pill" style="${colorCamelot(t.tonalidad)}">${esc(t.tonalidad)}</span>` : "";
        const enPill = t.energia != null ? ` <span class="mini-pill" style="${colorEnergia(t.energia)}">${t.energia}</span>` : "";
        return `<li data-i="${i}" class="${son ? "sonando-fila" : ""}">
            <span class="prep-num">${i + 1}</span>
            ${slot(t.id, 30)}
            <div class="prep-meta">
                <div class="prep-t1">${esc(t.titulo)}</div>
                <div class="prep-t2">${esc(t.artista)}${t.bpm != null ? " · " + t.bpm + " BPM" : ""}${keyPill}${enPill}</div>
            </div>
            <div class="prep-acc">
                <button data-acc="play" title="Escuchar">▶</button>
                <button data-acc="subir" title="Subir">↑</button>
                <button data-acc="bajar" title="Bajar">↓</button>
                <button data-acc="quitar" title="Quitar">✕</button>
            </div>
        </li>`;
    }).join("");
    const dur = prep.reduce((s, t) => s + (t.duracion || 0), 0);
    document.getElementById("prep-resumen").textContent =
        prep.length ? `${prep.length} canciones · ${fmtDur(dur)} de música` : "";
}

document.getElementById("prep-lista").addEventListener("click", e => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const i = +e.target.closest("li").dataset.i;
    const acc = btn.dataset.acc;
    if (acc === "play") reproducir(prep[i]);
    else if (acc === "quitar") { prep.splice(i, 1); renderPrep(); }
    else if (acc === "subir" && i > 0) { [prep[i - 1], prep[i]] = [prep[i], prep[i - 1]]; renderPrep(); }
    else if (acc === "bajar" && i < prep.length - 1) { [prep[i + 1], prep[i]] = [prep[i], prep[i + 1]]; renderPrep(); }
});

// soltar canciones en el panel
const panelPrep = document.getElementById("prep-panel");
panelPrep.addEventListener("dragover", e => { e.preventDefault(); panelPrep.classList.add("arrastrando"); });
panelPrep.addEventListener("dragleave", e => { if (!panelPrep.contains(e.relatedTarget)) panelPrep.classList.remove("arrastrando"); });
panelPrep.addEventListener("drop", e => {
    e.preventDefault();
    panelPrep.classList.remove("arrastrando");
    try { anadirAlSet(JSON.parse(e.dataTransfer.getData("text/plain"))); } catch (_) {}
});

// ordenar el set
document.getElementById("btn-orden-bpm").onclick = () => {
    prep.sort((a, b) => (a.bpm || 0) - (b.bpm || 0));
    renderPrep();
    toast("Set ordenado por BPM (de menor a mayor).", 1800);
};
document.getElementById("btn-orden-key").onclick = () => {
    // Orden por rueda Camelot: primero el número (1–12), luego la letra (A antes que B).
    const clave = t => {
        const m = (t.tonalidad || "").match(/^(\d{1,2})([AB])$/);
        if (!m) return [99, "Z"];           // sin tonalidad van al final
        return [parseInt(m[1], 10), m[2]];
    };
    prep.sort((a, b) => {
        const ka = clave(a), kb = clave(b);
        return ka[0] - kb[0] || ka[1].localeCompare(kb[1]);
    });
    renderPrep();
    toast("Set ordenado por tonalidad (rueda Camelot).", 1800);
};

// guardar / exportar / vaciar
async function guardarSet(silencioso) {
    const nombre = document.getElementById("nombre-set").value.trim();
    if (!nombre) { toast("Ponle un nombre al set antes de guardar."); return null; }
    if (!prep.length) { toast("El set está vacío."); return null; }
    const r = await post("/api/playlist", { nombre, track_ids: prep.map(t => t.id) });
    prepId = r.id;
    LISTAS = await api("/api/playlists");
    renderSidebar();
    if (!silencioso) toast(`Set "${nombre}" guardado con ${prep.length} canciones.`);
    return r.id;
}
document.getElementById("btn-guardar-set").onclick = () => guardarSet(false);
document.getElementById("btn-vaciar-set").onclick = () => {
    if (!prep.length) return;
    if (!confirm("¿Vaciar el set en preparación? (No borra ninguna lista guardada.)")) return;
    prep = []; prepId = null; document.getElementById("nombre-set").value = ""; renderPrep();
};
document.getElementById("btn-exportar-set").onclick = async () => {
    try {
        const id = await guardarSet(true);   // guardamos primero para exportar
        if (!id) return;
        const r = await post(`/api/playlist/${id}/exportar`, {});
        toast(`Exportado a la carpeta "exports":\n\n• Rekordbox:  ${r.rekordbox.split("\\").pop()}\n• Traktor:  ${r.traktor.split("\\").pop()}\n\nÁbrelos manualmente en cada programa (ver LEEME.txt).`, 11000);
    } catch (e) { toast("" + e.message); }
};

// =====================================================================
//  CARPETA / ESCANEO / BPM
// =====================================================================
document.getElementById("btn-elegir-carpeta").onclick = async () => {
    const btn = document.getElementById("btn-elegir-carpeta");
    btn.disabled = true; const orig = btn.textContent; btn.textContent = "Abriendo…";
    try {
        const r = await post("/api/elegir-carpeta", {});
        if (r.cancelado) toast("No elegiste ninguna carpeta.");
        else if (r.carpeta) toast(`Carpeta elegida:\n${r.carpeta}\n\nAhora pulsa «Escanear».`, 6000);
    } catch (e) { toast("" + e.message); }
    finally { btn.disabled = false; btn.textContent = orig; }
};
document.getElementById("btn-escanear").onclick = async () => {
    try { await post("/api/escanear", {}); vigilar("/api/escaneo/estado", "Escaneando"); }
    catch (e) { toast("" + e.message); }
};
document.getElementById("btn-bpm").onclick = async () => {
    try { await post("/api/bpm/calcular", {}); vigilar("/api/bpm/estado", "Calculando BPM"); }
    catch (e) { toast("" + e.message); }
};
function vigilar(urlEstado, etiqueta) {
    const cont = document.getElementById("progreso");
    const relleno = document.getElementById("progreso-relleno");
    const texto = document.getElementById("progreso-texto");
    cont.classList.remove("oculto");
    const iv = setInterval(async () => {
        const e = await api(urlEstado);
        const pct = e.total ? Math.round(e.procesados / e.total * 100) : 0;
        relleno.style.width = pct + "%";
        texto.textContent = `${etiqueta}: ${e.procesados}/${e.total} — ${e.mensaje || ""}`;
        if (!e.activo) {
            clearInterval(iv);
            texto.textContent = e.mensaje || "Listo.";
            setTimeout(() => cont.classList.add("oculto"), 2800);
            await recargarTrasProceso();
        }
    }, 600);
}
async function recargarTrasProceso() {
    TRACKS = await api("/api/tracks");
    PORID = new Map(TRACKS.map(t => [t.id, t]));
    GENEROS = await api("/api/generos");
    document.getElementById("lista-generos").innerHTML = GENEROS.map(g => `<option value="${esc(g)}">`).join("");
    // refrescar datos de las canciones que estén en el set
    prep = prep.map(t => PORID.get(t.id) || t).filter(Boolean);
    if (fuente.tipo === "playlist") { const pl = await api(`/api/playlist/${fuente.valor}`); fuente.tracks = pl.tracks; }
    renderSidebar(); renderNavegador(); renderPrep();
}

// =====================================================================
//  REPRODUCTOR (con waveform)
// =====================================================================
const audio = document.getElementById("audio-el");
const repBar = document.getElementById("reproductor");
const repCover = document.getElementById("rep-cover");
repCover.addEventListener("error", () => { repCover.style.visibility = "hidden"; });

const waveCanvas = document.getElementById("rep-wave");
const waveCtx = waveCanvas.getContext("2d");
const waveformCache = new Map();   // id -> array de picos normalizados 0..1
let waveformPeaks = null;
let waveformCargando = false;
let waveformIdActual = null;       // id del tema al que pertenecen los picos en curso/cargados

function dimensionarWaveCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const rect = waveCanvas.getBoundingClientRect();
    waveCanvas.width = Math.max(1, Math.round(rect.width * dpr));
    waveCanvas.height = Math.max(1, Math.round(rect.height * dpr));
}

function dibujarWaveform() {
    if (repBar.classList.contains("oculto")) return;
    dimensionarWaveCanvas();
    const w = waveCanvas.width, h = waveCanvas.height;
    waveCtx.clearRect(0, 0, w, h);
    const progreso = audio.duration ? audio.currentTime / audio.duration : 0;

    if (waveformCargando) {
        waveCtx.fillStyle = "rgba(255,255,255,.10)";
        waveCtx.fillRect(0, h / 2 - 1, w, 2);
        return;
    }
    if (!waveformPeaks) {
        // sin waveform disponible (formato no decodificable en el navegador): barra plana
        waveCtx.fillStyle = "rgba(255,255,255,.14)";
        waveCtx.fillRect(0, h / 2 - 2, w, 4);
        waveCtx.fillStyle = "#f6fc57";
        waveCtx.fillRect(0, h / 2 - 2, w * progreso, 4);
        return;
    }
    const n = waveformPeaks.length;
    const barW = w / n;
    for (let i = 0; i < n; i++) {
        const amp = Math.max(0.05, waveformPeaks[i]);
        const barH = amp * h;
        const reproducido = (i / n) <= progreso;
        waveCtx.fillStyle = reproducido ? "#f6fc57" : "rgba(255,255,255,.22)";
        waveCtx.fillRect(i * barW, (h - barH) / 2, Math.max(1, barW - 1), barH);
    }
}

async function generarWaveform(track) {
    waveformIdActual = track.id;
    const enCache = waveformCache.get(track.id);
    if (enCache) {
        waveformPeaks = enCache; waveformCargando = false; dibujarWaveform();
        return;
    }
    waveformPeaks = null; waveformCargando = true;
    dibujarWaveform();
    try {
        const resp = await fetch(`/api/audio/${track.id}`);
        const buf = await resp.arrayBuffer();
        if (waveformIdActual !== track.id) return;   // el usuario ya cambió de tema
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        const actx = new AudioCtx();
        const audioBuffer = await actx.decodeAudioData(buf);
        actx.close();
        if (waveformIdActual !== track.id) return;
        const raw = audioBuffer.getChannelData(0);
        const muestras = 220;
        const bloque = Math.max(1, Math.floor(raw.length / muestras));
        const picos = new Array(muestras).fill(0);
        for (let i = 0; i < muestras; i++) {
            let max = 0;
            const inicio = i * bloque;
            for (let j = 0; j < bloque; j++) {
                const v = Math.abs(raw[inicio + j] || 0);
                if (v > max) max = v;
            }
            picos[i] = max;
        }
        const picoMax = Math.max(...picos) || 1;
        const normalizados = picos.map(p => p / picoMax);
        waveformCache.set(track.id, normalizados);
        if (waveformIdActual === track.id) waveformPeaks = normalizados;
    } catch (e) {
        // Formato no decodificable por el navegador (p.ej. algún AIFF): caemos a la barra plana.
        waveformPeaks = null;
    } finally {
        if (waveformIdActual === track.id) { waveformCargando = false; dibujarWaveform(); }
    }
}

function seekDesdeEvento(e) {
    if (!audio.duration) return;
    const rect = waveCanvas.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    audio.currentTime = frac * audio.duration;
}
let arrastrandoWave = false;
waveCanvas.addEventListener("mousedown", e => { arrastrandoWave = true; seekDesdeEvento(e); });
window.addEventListener("mousemove", e => { if (arrastrandoWave) seekDesdeEvento(e); });
window.addEventListener("mouseup", () => { arrastrandoWave = false; });
waveCanvas.addEventListener("touchstart", e => { seekDesdeEvento(e); });
window.addEventListener("resize", () => dibujarWaveform());

// Averigua por qué falló la reproducción para dar un mensaje útil (no todo es
// "formato no soportado": lo más común es que el archivo se haya movido).
async function manejarErrorAudio(track) {
    if (!track) return;
    let existe = true;
    try {
        const r = await fetch(`/api/audio/${track.id}`, { method: "HEAD" });
        existe = r.ok;
    } catch (_) { existe = false; }
    const fmt = (track.formato || "audio").toUpperCase();
    if (!existe) {
        toast("El archivo ya no está en su ruta (¿lo moviste o renombraste?). Pulsa «Escanear» para actualizar la biblioteca.", 8000);
    } else if (["aiff", "aif"].includes((track.formato || "").toLowerCase())) {
        toast(`El formato AIFF no se puede reproducir aquí (tampoco en Chrome/Edge). Convierte esos temas a WAV/FLAC/MP3 si quieres oírlos. El archivo sigue intacto y el resto suena normal.`, 9000);
    } else {
        toast(`No se pudo reproducir este ${fmt} (el archivo sigue intacto).`, 7000);
    }
}

function reproducir(track) {
    if (!track) return;
    if (reproEl.actual === track.id) { audio.paused ? audio.play() : audio.pause(); return; }
    reproEl.actual = track.id;
    audio.src = `/api/audio/${track.id}`;
    // load() resetea el elemento y limpia cualquier estado de error previo. Sin
    // esto, un solo archivo no decodificable (p.ej. AIFF) deja el reproductor
    // bloqueado y NINGÚN tema siguiente vuelve a sonar hasta recargar.
    audio.load();
    // El evento 'error' del <audio> se encarga de diagnosticar los fallos reales.
    audio.play().catch(() => {});
    repBar.classList.remove("oculto");
    document.getElementById("rep-titulo").textContent = track.titulo || "(sin título)";
    document.getElementById("rep-artista").textContent = track.artista || "";
    repCover.style.visibility = "visible";
    repCover.src = `/api/cover/${track.id}`;
    generarWaveform(track);
    renderNavegador(); renderPrep();
}
document.getElementById("rep-play").onclick = () => { audio.paused ? audio.play() : audio.pause(); };
document.getElementById("rep-cerrar").onclick = () => {
    // actual = null ANTES de vaciar src, para que el 'error' de vaciar no dispare aviso.
    reproEl.actual = null; waveformIdActual = null; waveformPeaks = null;
    audio.pause(); audio.removeAttribute("src"); audio.load();
    repBar.classList.add("oculto"); renderNavegador(); renderPrep();
};
audio.addEventListener("error", () => {
    if (reproEl.actual == null) return;      // vaciado intencionado: no es un fallo real
    const t = PORID.get(reproEl.actual);
    // Soltamos el tema fallido para que no deje el reproductor "sonando" en falso;
    // el load() del siguiente tema ya limpia el estado de error del elemento.
    reproEl.actual = null;
    renderNavegador(); renderPrep();
    manejarErrorAudio(t);
});
audio.addEventListener("play", () => document.getElementById("rep-play").textContent = "⏸");
audio.addEventListener("pause", () => document.getElementById("rep-play").textContent = "▶");
audio.addEventListener("ended", () => { reproEl.actual = null; document.getElementById("rep-play").textContent = "▶"; renderNavegador(); renderPrep(); });
audio.addEventListener("loadedmetadata", () => document.getElementById("rep-total").textContent = fmtDur(audio.duration));
audio.addEventListener("timeupdate", () => {
    document.getElementById("rep-tiempo").textContent = fmtDur(audio.currentTime);
    dibujarWaveform();
});
const vol = document.getElementById("rep-volumen");
audio.volume = vol.value / 100;
vol.addEventListener("input", () => audio.volume = vol.value / 100);

// =====================================================================
//  MODAL GENÉRICO
// =====================================================================
const modalFondo = document.getElementById("modal-fondo");
function abrirModal(titulo, cuerpoHTML, pieHTML) {
    document.getElementById("modal-titulo").textContent = titulo;
    document.getElementById("modal-cuerpo").innerHTML = cuerpoHTML;
    document.getElementById("modal-pie").innerHTML = pieHTML || "";
    modalFondo.classList.remove("oculto");
}
function cerrarModal() { modalFondo.classList.add("oculto"); }
document.getElementById("modal-cerrar").onclick = cerrarModal;
modalFondo.addEventListener("click", e => { if (e.target === modalFondo) cerrarModal(); });

function ocupar(btn, texto) {
    if (!btn) return () => {};
    const orig = btn.textContent; const dis = btn.disabled;
    btn.disabled = true; btn.textContent = texto || "Pensando…";
    return () => { btn.disabled = dis; btn.textContent = orig; };
}

// =====================================================================
//  AJUSTES DE IA (Groq gratis por defecto, OpenRouter como extra)
// =====================================================================
document.getElementById("btn-ajustes").onclick = async () => {
    const a = await api("/api/ia/ajustes");   // { activo, proveedores: [...] }
    const bloque = p => `
        <div class="ia-prov ${p.id === a.activo ? "activo" : ""}">
            <label class="ia-prov-cab">
                <input type="radio" name="ia-prov" value="${p.id}" ${p.id === a.activo ? "checked" : ""}>
                <b>${esc(p.nombre)}</b>
                ${p.configurada ? `<span class="ia-ok">clave ${esc(p.clave_pista)}</span>` : ""}
            </label>
            <input type="password" id="clave-${p.id}" placeholder="${p.configurada ? "Guardada — escribe para cambiarla" : esc(p.pista_clave)}">
            <input type="text" id="modelo-${p.id}" value="${esc(p.modelo)}" list="modelos-${p.id}" title="Modelo (por defecto ${esc(p.modelo_defecto)})">
            <datalist id="modelos-${p.id}">${(p.modelos_sugeridos || []).map(m => `<option value="${esc(m)}">`).join("")}</datalist>
            <a href="#" class="ia-link" data-url="${esc(p.url_clave)}">Consigue tu clave gratis →</a>
        </div>`;
    abrirModal("Ajustes de IA", `
        <p class="ayuda">La IA es opcional. Solo se envía texto (artista, título, género…), <b>nunca tu música</b>. Por defecto usa <b>Groq</b>, que es gratis (crea tu clave gratuita en 30 s). OpenRouter es un extra para modelos de pago. Todo se guarda solo en tu ordenador.</p>
        ${a.proveedores.map(bloque).join("")}
        <p id="ajustes-msg" class="msg"></p>
    `, `
        <button id="btn-probar-ia" class="btn">Probar</button>
        <button id="btn-guardar-ia" class="btn primario">Guardar</button>
    `);
    document.querySelectorAll(".ia-link").forEach(el => el.onclick = async (ev) => {
        ev.preventDefault();
        try { await post("/api/abrir-url", { url: el.dataset.url }); }
        catch (_) { toast("Abre: " + el.dataset.url, 6000); }
    });
    const recoger = () => {
        const d = { proveedor: document.querySelector('input[name="ia-prov"]:checked').value };
        a.proveedores.forEach(p => {
            d[`${p.id}_clave`] = document.getElementById(`clave-${p.id}`).value;
            d[`${p.id}_modelo`] = document.getElementById(`modelo-${p.id}`).value;
        });
        return d;
    };
    document.getElementById("btn-guardar-ia").onclick = async () => {
        await post("/api/ia/ajustes", recoger());
        toast("Ajustes de IA guardados.");
        cerrarModal();
    };
    document.getElementById("btn-probar-ia").onclick = async (e) => {
        await post("/api/ia/ajustes", recoger());
        const msg = document.getElementById("ajustes-msg");
        const rest = ocupar(e.target, "Probando…");
        try {
            await post("/api/ia/probar", {});
            msg.className = "msg ok"; msg.textContent = "Conexión correcta.";
        } catch (err) { msg.className = "msg error"; msg.textContent = err.message; }
        finally { rest(); }
    };
};

// =====================================================================
//  IA: arreglar nombres / sugerir género (sobre la selección)
// =====================================================================
document.getElementById("btn-ia-nombres").onclick = async (e) => {
    const ids = [...seleccion];
    if (!ids.length) { toast("Selecciona canciones primero."); return; }
    const rest = ocupar(e.target, "Pensando…");
    try {
        const r = await post("/api/ia/arreglar-nombres", { ids });
        revisarNombres(r.propuestas);
    } catch (err) { toast("" + err.message); }
    finally { rest(); }
};
function revisarNombres(props) {
    const cambios = props.filter(p =>
        p.artista !== p.artista_actual || p.titulo !== p.titulo_actual);
    if (!cambios.length) { toast("La IA no encontró nombres que corregir."); return; }
    const filas = cambios.map((p, i) => `
        <tr>
            <td><input type="checkbox" class="chk-prop" data-i="${i}" checked></td>
            <td><div class="antes">${esc(p.artista_actual)} — ${esc(p.titulo_actual)}</div>
                <div class="despues">${esc(p.artista)} — ${esc(p.titulo)}</div></td>
        </tr>`).join("");
    abrirModal(`Revisar nombres (${cambios.length})`,
        `<p class="ayuda">Marca los cambios que quieras aplicar. Se escribirán en las etiquetas de los archivos.</p>
         <table class="tabla-prop"><tbody>${filas}</tbody></table>`,
        `<button id="btn-aplicar-props" class="btn primario">Aplicar seleccionados</button>`);
    document.getElementById("btn-aplicar-props").onclick = async (ev) => {
        const rest = ocupar(ev.target, "Aplicando…");
        const marcados = [...document.querySelectorAll(".chk-prop:checked")].map(c => cambios[+c.dataset.i]);
        for (const p of marcados) {
            try {
                if (p.artista !== p.artista_actual) await post(`/api/track/${p.id}/campo`, { campo: "artista", valor: p.artista });
                if (p.titulo !== p.titulo_actual) await post(`/api/track/${p.id}/campo`, { campo: "titulo", valor: p.titulo });
                const t = PORID.get(p.id); if (t) { t.artista = p.artista; t.titulo = p.titulo; }
            } catch (err) { toast("" + err.message); }
        }
        rest(); cerrarModal(); renderNavegador();
        toast(`Aplicados ${marcados.length} cambios de nombre.`);
    };
}

document.getElementById("btn-ia-genero").onclick = async (e) => {
    const ids = [...seleccion];
    if (!ids.length) { toast("Selecciona canciones primero."); return; }
    const rest = ocupar(e.target, "Pensando…");
    try {
        const r = await post("/api/ia/sugerir-genero", { ids });
        revisarGeneros(r.propuestas);
    } catch (err) { toast("" + err.message); }
    finally { rest(); }
};
function revisarGeneros(props) {
    const cambios = props.filter(p => p.genero && p.genero !== p.genero_actual);
    if (!cambios.length) { toast("La IA no sugirió géneros nuevos."); return; }
    const filas = cambios.map((p, i) => {
        const t = PORID.get(p.id) || {};
        return `<tr>
            <td><input type="checkbox" class="chk-prop" data-i="${i}" checked></td>
            <td>${esc(t.artista)} — ${esc(t.titulo)}</td>
            <td><span class="antes">${esc(p.genero_actual) || "(vacío)"}</span> → <span class="despues">${esc(p.genero)}</span></td>
        </tr>`;
    }).join("");
    abrirModal(`Revisar géneros (${cambios.length})`,
        `<p class="ayuda">Marca los que quieras aplicar. Se escribirán en las etiquetas de los archivos.</p>
         <table class="tabla-prop"><tbody>${filas}</tbody></table>`,
        `<button id="btn-aplicar-props" class="btn primario">Aplicar seleccionados</button>`);
    document.getElementById("btn-aplicar-props").onclick = async (ev) => {
        const rest = ocupar(ev.target, "Aplicando…");
        const marcados = [...document.querySelectorAll(".chk-prop:checked")].map(c => cambios[+c.dataset.i]);
        for (const p of marcados) {
            try {
                await post(`/api/track/${p.id}/genero`, { genero: p.genero });
                const t = PORID.get(p.id); if (t) t.genero = p.genero;
            } catch (err) { toast("" + err.message); }
        }
        GENEROS = await api("/api/generos");
        rest(); cerrarModal(); renderSidebar(); renderNavegador();
        toast(`Aplicados ${marcados.length} géneros.`);
    };
}

// =====================================================================
//  IA: recomendar temas / armar set por descripción
// =====================================================================
async function recomendarDesde(ids, boton) {
    if (!ids || !ids.length) { toast("No hay temas de partida para recomendar."); return; }
    const rest = boton ? ocupar(boton, "Pensando…") : null;
    try {
        const r = await post("/api/ia/recomendar", { ids });
        mostrarRecomendaciones(r.tracks);
    } catch (err) { toast("" + err.message); }
    finally { if (rest) rest(); }
}
document.getElementById("btn-ia-recomendar").onclick = (e) => {
    let ids = prep.map(t => t.id);
    if (!ids.length) ids = [...seleccion];
    if (!ids.length) { toast("Añade temas al set (o selecciona alguno) para recomendar a partir de ellos."); return; }
    recomendarDesde(ids, e.target);
};
function mostrarRecomendaciones(tracks) {
    if (!tracks.length) { toast("La IA no encontró recomendaciones claras."); return; }
    const filas = tracks.map(t => `
        <tr data-id="${t.id}">
            <td>${slot(t.id, 30)}</td>
            <td><div class="prep-t1">${esc(t.titulo)}</div>
                <div class="prep-t2">${esc(t.artista)}${t.bpm != null ? " · " + t.bpm + " BPM" : ""}${t.tonalidad ? " · " + esc(t.tonalidad) : ""}</div>
                <div class="motivo">${esc(t.motivo)}</div></td>
            <td><button class="btn-icono btn-rec-add" title="Añadir al set">＋</button></td>
        </tr>`).join("");
    abrirModal("Recomendaciones para tu set",
        `<table class="tabla-prop tabla-rec"><tbody>${filas}</tbody></table>`,
        `<button id="btn-rec-todas" class="btn primario">Añadir todas al set</button>`);
    const porId = new Map(tracks.map(t => [t.id, t]));
    document.getElementById("modal-cuerpo").addEventListener("click", ev => {
        const btn = ev.target.closest(".btn-rec-add");
        if (!btn) return;
        const id = +ev.target.closest("tr").dataset.id;
        if (!PORID.has(id)) PORID.set(id, porId.get(id));
        anadirAlSet([id]);
        btn.textContent = "✓"; btn.disabled = true;
    });
    document.getElementById("btn-rec-todas").onclick = () => {
        tracks.forEach(t => { if (!PORID.has(t.id)) PORID.set(t.id, t); });
        anadirAlSet(tracks.map(t => t.id));
        cerrarModal();
    };
}

document.getElementById("btn-armar-set").onclick = async (e) => {
    const descripcion = document.getElementById("desc-set").value.trim();
    if (!descripcion) { toast("Describe el set que quieres (género, ambiente, BPM…)."); return; }
    const rest = ocupar(e.target, "…");
    try {
        const r = await post("/api/ia/armar-set", { descripcion });
        if (!r.tracks.length) { toast("La IA no encontró temas para esa descripción."); return; }
        r.tracks.forEach(t => PORID.set(t.id, t));
        prep = r.tracks.slice();
        renderPrep();
        toast(`Set armado con ${r.tracks.length} temas. Revísalo, reordena y guarda.`, 6000);
    } catch (err) { toast("" + err.message); }
    finally { rest(); }
};

// =====================================================================
//  CHAT CON LA IA
// =====================================================================
let chatHistorial = [];
const chatDrawer = document.getElementById("chat-drawer");
const chatMensajes = document.getElementById("chat-mensajes");
const chatInput = document.getElementById("chat-input");

document.getElementById("btn-chat").onclick = () => {
    chatDrawer.classList.toggle("oculto");
    if (!chatDrawer.classList.contains("oculto")) {
        if (!chatHistorial.length) pintarBienvenidaChat();
        chatInput.focus();
    }
};
document.getElementById("chat-cerrar").onclick = () => chatDrawer.classList.add("oculto");
document.getElementById("chat-limpiar").onclick = () => {
    chatHistorial = []; chatMensajes.innerHTML = ""; pintarBienvenidaChat();
};

function pintarBienvenidaChat() {
    burbuja("assistant", "¡Hola! Soy tu asistente. Conozco tu colección: pídeme que te arme un set, que busque temas por género/BPM/tonalidad, o que te sugiera géneros. Por ejemplo: «ármame un warm-up melódico de 120 a 124».");
}

function burbuja(rol, texto, ids) {
    const div = document.createElement("div");
    div.className = "chat-burbuja " + (rol === "user" ? "chat-user" : "chat-ia");
    div.innerHTML = `<div class="chat-txt"></div>`;
    div.querySelector(".chat-txt").textContent = texto;
    if (ids && ids.length) {
        const cont = document.createElement("div");
        cont.className = "chat-accion";
        cont.innerHTML = `<button class="btn ia chat-cargar">➕ Cargar ${ids.length} temas en el set</button>`;
        cont.querySelector("button").onclick = () => {
            const validos = ids.filter(id => PORID.has(id));
            if (!validos.length) { toast("Esos temas no están en la biblioteca."); return; }
            validos.forEach(id => { if (!prep.some(t => t.id === id)) prep.push(PORID.get(id)); });
            renderPrep();
            toast(`Añadidos ${validos.length} temas al set.`);
        };
        div.appendChild(cont);
    }
    chatMensajes.appendChild(div);
    chatMensajes.scrollTop = chatMensajes.scrollHeight;
    return div;
}

// separa el texto visible de la línea "SET: [..]" con los ids propuestos
function extraerSet(texto) {
    const m = texto.match(/SET:\s*\[([0-9,\s]*)\]\s*$/i);
    if (!m) return { visible: texto, ids: [] };
    const ids = m[1].split(",").map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n));
    return { visible: texto.slice(0, m.index).trim(), ids };
}

async function enviarChat() {
    const texto = chatInput.value.trim();
    if (!texto) return;
    chatInput.value = ""; chatInput.style.height = "auto";
    burbuja("user", texto);
    chatHistorial.push({ role: "user", content: texto });

    const pensando = burbuja("assistant", "…");
    pensando.querySelector(".chat-txt").classList.add("pensando");
    try {
        const r = await post("/api/ia/chat", { mensajes: chatHistorial });
        const { visible, ids } = extraerSet(r.respuesta);
        chatHistorial.push({ role: "assistant", content: r.respuesta });
        pensando.remove();
        burbuja("assistant", visible || "(sin texto)", ids);
    } catch (e) {
        pensando.remove();
        burbuja("assistant", "" + e.message);
    }
}
document.getElementById("chat-enviar").onclick = enviarChat;
chatInput.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviarChat(); }
});
// autoajuste de altura del textarea
chatInput.addEventListener("input", () => {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + "px";
});

// =====================================================================
//  MENÚ CONTEXTUAL (clic derecho sobre una canción)
// =====================================================================
const menuCtx = document.getElementById("menu-contextual");
let menuCtxId = null;

function ocultarMenuCtx() { menuCtx.classList.add("oculto"); menuCtxId = null; }

function mostrarMenuCtx(x, y) {
    menuCtx.classList.remove("oculto");
    const r = menuCtx.getBoundingClientRect();
    menuCtx.style.left = Math.min(x, window.innerWidth - r.width - 8) + "px";
    menuCtx.style.top = Math.min(y, window.innerHeight - r.height - 8) + "px";
}

document.getElementById("cuerpo-tracks").addEventListener("contextmenu", e => {
    const tr = e.target.closest("tr");
    if (!tr) return;
    e.preventDefault();
    menuCtxId = +tr.dataset.id;
    const t = PORID.get(menuCtxId);
    if (!t) return;
    const items = [
        { txt: "Reproducir", acc: "play" },
        { txt: "Añadir al set", acc: "add" },
        { sep: true },
        { txt: "Recomendar a partir de esta", acc: "recomendar" },
        { txt: `Ver todo de «${t.artista || "este artista"}»`, acc: "artista" },
        { sep: true },
        { txt: "Editar género", acc: "genero" },
        { txt: "Abrir ubicación del archivo", acc: "abrir" },
        { txt: "Copiar ruta del archivo", acc: "copiar" },
    ];
    menuCtx.innerHTML = items.map(it => it.sep
        ? `<div class="menu-ctx-sep"></div>`
        : `<button class="menu-ctx-item" data-acc="${it.acc}">${esc(it.txt)}</button>`
    ).join("");
    mostrarMenuCtx(e.clientX, e.clientY);
});

menuCtx.addEventListener("click", async e => {
    const btn = e.target.closest(".menu-ctx-item");
    if (!btn) return;
    e.stopPropagation();
    const id = menuCtxId, acc = btn.dataset.acc, t = PORID.get(id);
    ocultarMenuCtx();
    if (!t) return;
    if (acc === "play") reproducir(t);
    else if (acc === "add") anadirAlSet([id]);
    else if (acc === "recomendar") recomendarDesde([id]);
    else if (acc === "artista") { document.getElementById("buscar").value = t.artista || ""; renderNavegador(); }
    else if (acc === "genero") {
        const celda = document.querySelector(`#cuerpo-tracks tr[data-id="${id}"] .celda-genero`);
        if (celda) editarGenero(celda, id); else toast("Esa canción no está en la vista actual.");
    }
    else if (acc === "abrir") {
        try { await post(`/api/track/${id}/abrir-carpeta`, {}); }
        catch (err) { toast("" + err.message); }
    }
    else if (acc === "copiar") {
        try { await navigator.clipboard.writeText(t.ruta || ""); toast("Ruta copiada al portapapeles.", 1800); }
        catch (_) { toast("Ruta del archivo:\n" + (t.ruta || "(desconocida)"), 6000); }
    }
});

// cerrar el menú al hacer clic fuera, hacer scroll, redimensionar o pulsar Escape
document.addEventListener("click", ocultarMenuCtx);
document.addEventListener("scroll", ocultarMenuCtx, true);
window.addEventListener("resize", ocultarMenuCtx);
document.addEventListener("keydown", e => { if (e.key === "Escape") ocultarMenuCtx(); });

// =====================================================================
//  ARRASTRAR ARCHIVOS DESDE EL EXPLORADOR (importar a la carpeta de música)
// =====================================================================
const dropOverlay = document.getElementById("drop-overlay");
let dragDepth = 0;

function esArrastreDeArchivos(e) {
    return e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
}

// Recorre lo soltado; si son carpetas, entra en ellas conservando la estructura.
function recorrerEntry(entry, prefijo, salida) {
    return new Promise(resolve => {
        if (!entry) { resolve(); return; }
        if (entry.isFile) {
            entry.file(
                file => { salida.push({ file, path: prefijo + entry.name }); resolve(); },
                () => resolve()
            );
        } else if (entry.isDirectory) {
            const reader = entry.createReader();
            const leerLote = () => reader.readEntries(async entradas => {
                if (!entradas.length) { resolve(); return; }
                for (const sub of entradas) await recorrerEntry(sub, prefijo + entry.name + "/", salida);
                leerLote();   // readEntries devuelve en lotes; hay que llamar hasta vaciar
            }, () => resolve());
            leerLote();
        } else resolve();
    });
}

async function recolectarArchivos(dataTransfer) {
    const salida = [];
    const items = dataTransfer.items;
    const soportaEntries = items && items.length && items[0].webkitGetAsEntry;
    if (soportaEntries) {
        const entries = [];
        for (const it of items) {
            const en = it.webkitGetAsEntry && it.webkitGetAsEntry();
            if (en) entries.push(en);
        }
        for (const en of entries) await recorrerEntry(en, "", salida);
    } else {
        for (const f of dataTransfer.files) salida.push({ file: f, path: f.name });
    }
    return salida;
}

const EXT_AUDIO = [".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".ogg"];

async function importarSoltados(dataTransfer) {
    if (!RAIZ) {
        toast("Primero elige tu carpeta de música ( arriba) para poder importar en ella.", 6000);
        return;
    }
    let items;
    try { items = await recolectarArchivos(dataTransfer); }
    catch (_) { items = [...(dataTransfer.files || [])].map(f => ({ file: f, path: f.name })); }
    const audios = items.filter(x => EXT_AUDIO.some(ext => x.path.toLowerCase().endsWith(ext)));
    if (!audios.length) { toast("No había archivos de audio en lo que soltaste.", 4000); return; }

    const fd = new FormData();
    audios.forEach(x => { fd.append("archivos", x.file); fd.append("rutas", x.path); });
    toast(`Importando ${audios.length} archivo(s)…`, 3000);
    try {
        const r = await api("/api/importar", { method: "POST", body: fd });
        const nota = r.ignorados ? ` (${r.ignorados} ignorados)` : "";
        toast(`Importados ${r.guardados} archivo(s)${nota}. Escaneando para añadirlos…`, 4000);
        await post("/api/escanear", {});
        vigilar("/api/escaneo/estado", "Escaneando");
    } catch (e) { toast("" + e.message, 6000); }
}

window.addEventListener("dragenter", e => {
    if (!esArrastreDeArchivos(e)) return;
    e.preventDefault();
    dragDepth++;
    dropOverlay.classList.remove("oculto");
});
window.addEventListener("dragover", e => {
    if (!esArrastreDeArchivos(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
});
window.addEventListener("dragleave", e => {
    if (!esArrastreDeArchivos(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) dropOverlay.classList.add("oculto");
});
window.addEventListener("drop", e => {
    if (!esArrastreDeArchivos(e)) return;   // los arrastres internos (fila→set) no se tocan
    e.preventDefault();
    dragDepth = 0;
    dropOverlay.classList.add("oculto");
    importarSoltados(e.dataTransfer);
});

// =====================================================================
//  COMPROBADOR DE ACTUALIZACIONES
// =====================================================================
async function comprobarActualizacion() {
    let r;
    try { r = await api("/api/actualizacion"); }
    catch (_) { return; }                       // sin internet / repo privado: silencio
    if (!r || !r.ok || !r.hay_nueva) return;
    if (localStorage.getItem("update_omitir") === r.version_ultima) return;  // ya la descartaste

    const banner = document.getElementById("banner-update");
    document.getElementById("banner-update-txt").textContent =
        `Hay una versión nueva de MusicHub (v${r.version_ultima}). Tú tienes la v${r.version_actual}.`;
    banner.classList.remove("oculto");

    document.getElementById("banner-update-descargar").onclick = async () => {
        const url = r.url_descarga || r.url_release;
        if (!url) { toast("No encuentro el archivo de descarga para tu sistema."); return; }
        try { await post("/api/abrir-url", { url }); toast("Abriendo la descarga en tu navegador. Descomprime y reemplaza la carpeta del programa.", 8000); }
        catch (e) { toast("" + e.message); }
    };
    document.getElementById("banner-update-notas").onclick = async () => {
        if (r.url_release) { try { await post("/api/abrir-url", { url: r.url_release }); } catch (_) {} }
    };
    document.getElementById("banner-update-cerrar").onclick = () => {
        localStorage.setItem("update_omitir", r.version_ultima);   // no volver a avisar de ESTA versión
        banner.classList.add("oculto");
    };
}

// =====================================================================
//  ARRANQUE
// =====================================================================
cargarTodo();
comprobarActualizacion();
