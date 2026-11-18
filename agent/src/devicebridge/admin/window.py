from __future__ import annotations

import threading
from pathlib import Path

from devicebridge.admin.configuration import apply_preview, prepare_scanner_update
from devicebridge.config import ConfigurationError, load_configuration
from devicebridge.devices.scanners.discovery import discover_scanners


def open_configuration_window(config_path: Path) -> None:
    """Run a small native UI from the interactive Windows user session."""
    thread = threading.Thread(target=_run_window, args=(config_path,), daemon=True)
    thread.start()


def _run_window(config_path: Path) -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    configuration = load_configuration(config_path)
    root = tk.Tk()
    root.title("DeviceBridge — Configuración de escáner")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=16)
    frame.grid()

    scanners = {scanner.identifier: scanner for scanner in configuration.scanners}
    scanner_names = [f"{scanner.display_name} ({scanner.identifier})" for scanner in scanners.values()]
    selected = tk.StringVar(value=scanner_names[0] if scanner_names else "")
    ttk.Label(frame, text="Escáner configurado").grid(column=0, row=0, sticky="w")
    scanner_box = ttk.Combobox(frame, values=scanner_names, textvariable=selected, width=50, state="readonly")
    scanner_box.grid(column=0, row=1, columnspan=2, sticky="ew", pady=(0, 10))

    quality = tk.StringVar()
    source = tk.StringVar()
    color = tk.StringVar()
    output = tk.StringVar()
    duplex = tk.BooleanVar()
    detected = tk.StringVar(value="Pulse Detectar para buscar fuentes WIA y TWAIN.")

    def current_scanner():
        index = scanner_names.index(selected.get())
        return list(scanners.values())[index]

    def load_defaults(*_args):
        scanner = current_scanner()
        source.set(scanner.default_source)
        color.set(scanner.default_color_mode)
        quality.set(str(scanner.default_resolution))
        output.set(scanner.default_output_format)
        duplex.set(scanner.default_duplex)

    scanner_box.bind("<<ComboboxSelected>>", load_defaults)
    load_defaults()

    row = 2
    for label, variable, values in (
        ("Fuente", source, ("adf", "flatbed")),
        ("Color", color, ("color", "grayscale", "black_and_white")),
        ("Resolución", quality, ("150", "200", "300", "600")),
        ("Formato", output, ("pdf", "jpeg", "png")),
    ):
        ttk.Label(frame, text=label).grid(column=0, row=row, sticky="w")
        ttk.Combobox(frame, textvariable=variable, values=values, width=20, state="readonly").grid(
            column=1, row=row, sticky="ew", pady=2
        )
        row += 1
    ttk.Checkbutton(frame, text="Escaneo dúplex", variable=duplex).grid(column=0, row=row, columnspan=2, sticky="w", pady=4)
    row += 1

    ttk.Label(frame, textvariable=detected, wraplength=460, justify="left").grid(column=0, row=row, columnspan=2, sticky="w", pady=(8, 4))

    def detect():
        devices, diagnostics = discover_scanners()
        entries = [f"{device.technology}: {device.name}" for device in devices]
        detected.set("Detectados: " + (", ".join(entries) if entries else "ninguno") +
                     ("\n" + "\n".join(diagnostics) if diagnostics else ""))

    def preview_and_apply():
        scanner = current_scanner()
        values = {
            "default_source": source.get(), "default_color_mode": color.get(),
            "default_resolution": int(quality.get()), "default_output_format": output.get(),
            "default_duplex": duplex.get(),
        }
        try:
            preview = prepare_scanner_update(config_path, scanner.identifier, values)
        except (ConfigurationError, OSError, ValueError) as error:
            messagebox.showerror("Configuración no válida", str(error), parent=root)
            return
        if not preview.diff:
            messagebox.showinfo("Sin cambios", "La configuración ya contiene estos valores.", parent=root)
            return
        if messagebox.askyesno("Confirmar cambio", f"Cambios propuestos:\n\n{preview.diff}\n¿Aplicarlos?", parent=root):
            try:
                backup = apply_preview(preview)
            except (ConfigurationError, OSError) as error:
                messagebox.showerror("No se aplicó", str(error), parent=root)
                return
            messagebox.showinfo("Configuración guardada", f"Respaldo creado: {backup.name}\nReinicie el agente para aplicar los valores.", parent=root)

    ttk.Button(frame, text="Detectar escáneres", command=detect).grid(column=0, row=row + 1, sticky="w", pady=(12, 0))
    ttk.Button(frame, text="Vista previa y aplicar", command=preview_and_apply).grid(column=1, row=row + 1, sticky="e", pady=(12, 0))
    root.mainloop()
