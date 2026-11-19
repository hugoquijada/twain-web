from __future__ import annotations

import threading
import time
import webbrowser
import os
import sys
from pathlib import Path


def run_tray(server, admin_url: str, version: str, cancel_all, restart) -> None:
    """Show runtime state and open the local configuration window on Windows."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError("Faltan las dependencias de bandeja: pystray y Pillow.") from error

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Scanner silhouette: sheet, dark body, control light and output tray.
    draw.rounded_rectangle((7, 18, 57, 51), radius=7, fill=(15, 47, 64, 255))
    draw.rounded_rectangle((15, 8, 49, 31), radius=3, fill=(241, 245, 249, 255))
    draw.line((20, 15, 44, 15), fill=(148, 163, 184, 255), width=2)
    draw.line((20, 20, 39, 20), fill=(148, 163, 184, 255), width=2)
    draw.ellipse((47, 25, 51, 29), fill=(52, 211, 153, 255))
    draw.rounded_rectangle((16, 38, 48, 56), radius=3, fill=(255, 255, 255, 255))
    draw.line((22, 45, 42, 45), fill=(148, 163, 184, 255), width=2)

    def configure(icon, item) -> None:
        webbrowser.open(admin_url)

    def view_api(icon, item) -> None:
        base_url = admin_url.split("/admin", 1)[0]
        webbrowser.open(f"{base_url}/docs")

    def exit_agent(icon, item) -> None:
        server.should_exit = True
        icon.stop()

    def cancel_scans(icon, item) -> None:
        result = cancel_all()
        message = f"Se cancelaron {result['cancelled']} pendientes."
        if result["cancellationRequested"]:
            message += f" Se solicitó detener {result['cancellationRequested']} captura(s) activa(s)."
        try:
            icon.notify(message, "Puente Escáner")
        except Exception:
            pass

    def restart_agent(icon, item) -> None:
        server.should_exit = True
        icon.stop()
        restart()

    menu = pystray.Menu(
        pystray.MenuItem(f"Puente Escáner · versión {version}", None, enabled=False),
        pystray.MenuItem("Configurar escáner…", configure, default=True),
        pystray.MenuItem("Ver API", view_api),
        pystray.MenuItem("Cancelar todos los escaneos", cancel_scans),
        pystray.MenuItem("Reiniciar agente", restart_agent),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Salir", exit_agent),
    )
    icon = pystray.Icon("puente-escaner", image, f"Puente Escáner {version}", menu)
    icon.run()


def start_server_with_tray(uvicorn, application, host: str, port: int, admin_url: str, version: str) -> None:
    # The packaged application is built with --noconsole, where sys.stderr is
    # None. Uvicorn's default logging formatter calls stderr.isatty(), causing
    # startup to fail before the tray icon can be shown.
    config = uvicorn.Config(
        application,
        host=host,
        port=port,
        log_config=None,
        access_log=False,
    )
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
    def restart() -> None:
        thread.join(timeout=10)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    run_tray(server, admin_url, version, application.state.scan_jobs.cancel_all, restart)
