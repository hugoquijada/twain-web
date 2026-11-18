from __future__ import annotations

import threading
import time
from pathlib import Path


def run_tray(server, config_path: Path) -> None:
    """Show runtime state and open the local configuration window on Windows."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError("Faltan las dependencias de bandeja: pystray y Pillow.") from error

    from devicebridge.admin.window import open_configuration_window

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=(29, 142, 75, 255))
    draw.rectangle((28, 18, 36, 46), fill=(255, 255, 255, 255))
    draw.rectangle((18, 28, 46, 36), fill=(255, 255, 255, 255))

    def configure(icon, item) -> None:
        open_configuration_window(config_path)

    def exit_agent(icon, item) -> None:
        server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("DeviceBridge activo", None, enabled=False),
        pystray.MenuItem("Configurar escáner…", configure, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Salir", exit_agent),
    )
    icon = pystray.Icon("devicebridge", image, "DeviceBridge activo", menu)
    icon.run()


def start_server_with_tray(uvicorn, application, host: str, port: int, config_path: Path) -> None:
    config = uvicorn.Config(application, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="devicebridge-http", daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        if server.should_exit:
            raise RuntimeError("El agente HTTP no pudo iniciar; revise que el puerto esté disponible.")
        time.sleep(0.1)
    if not server.started:
        server.should_exit = True
        raise RuntimeError("El agente HTTP no inició dentro del tiempo esperado.")
    run_tray(server, config_path)
