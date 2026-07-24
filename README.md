# MusicHub

Organizador de música para DJ. Escanea tu colección, calcula **BPM, tonalidad
(Camelot) y energía**, corrige géneros, prepara sets con mezcla armónica y los
exporta a **Rekordbox** y **Traktor**. Incluye ayuda con IA (gratis) y funciona
en tu ordenador: **tu música nunca sale de tu equipo**.

## Descargar

Ve a la página de **[Releases](../../releases/latest)** y descarga:

| Sistema | Archivo | Cómo se instala |
|---|---|---|
| **Windows** | `MusicHub-Windows-Setup.exe` | Doble clic → siguiente → listo. Crea acceso directo. |
| **macOS** (Apple Silicon) | `MusicHub-macOS.dmg` | Ábrelo y arrastra **MusicHub** a **Aplicaciones**. |

La primera vez, el sistema puede avisar de que es de un desarrollador no
identificado (la app no está firmada con un certificado de pago):

- **Windows:** en el aviso de SmartScreen, pulsa *Más información → Ejecutar de
  todas formas*.
- **macOS:** clic **derecho** sobre MusicHub → **Abrir** (solo la primera vez).

## Qué hace

- Lee toda tu carpeta de música (MP3, FLAC, WAV, AIFF, M4A, OGG).
- Calcula **BPM**, **tonalidad** (rueda Camelot) y **energía** (1–10).
- Edita y **consolida géneros** (limpia duplicados) y lo escribe en los archivos.
- Prepara sets ordenando por BPM y tonalidad; los exporta a Rekordbox (.m3u8) y
  Traktor (.nml).
- Reproductor con forma de onda. Arrastra archivos/carpetas para importarlos.
- **IA opcional y gratis** (Groq): limpiar nombres, sugerir géneros, recomendar
  y armar sets. OpenRouter disponible como extra. Solo se envía texto, nunca audio.

Tus datos (biblioteca, listas, ajustes) se guardan en tu carpeta de usuario,
separados del programa.

## Compilar desde el código (avanzado)

Requiere Python 3. Windows: ejecuta `MusicHub.bat`. macOS/Linux: `MusicHub.command`.
La primera vez instala las dependencias en un entorno virtual y arranca en su
propia ventana.
