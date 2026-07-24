"""
elegir_carpeta.py — Abre el explorador de carpetas nativo de Windows.

Se ejecuta como proceso independiente desde el servidor (app.py). Muestra el
diálogo "Buscar carpeta", y al elegir una, imprime su ruta por la salida
estándar. Si el usuario cancela, no imprime nada.

Se lanza aparte (y no dentro del servidor) porque tkinter necesita su propio
hilo principal para funcionar de forma estable.
"""

import sys
import tkinter as tk
from tkinter import filedialog


def main():
    root = tk.Tk()
    root.withdraw()                       # ocultar la ventana raíz
    root.attributes("-topmost", True)     # el diálogo por encima del navegador
    root.update()

    carpeta = filedialog.askdirectory(
        title="Elige tu carpeta de música",
        mustexist=True,
    )
    root.destroy()

    if carpeta:
        # tkinter devuelve barras normales; las dejamos tal cual, Python las
        # entiende igual en Windows.
        sys.stdout.write(carpeta)


if __name__ == "__main__":
    main()
