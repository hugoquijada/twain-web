from __future__ import annotations

import argparse
import os
import platform
import sys
from pathlib import Path

import uvicorn

from devicebridge.api.app import create_app
from devicebridge.admin.tray import start_server_with_tray
from devicebridge.config import load_configuration
from devicebridge import __version__


def main() -> None:
    parser = argparse.ArgumentParser(description="DeviceBridge local agent")
    parser.add_argument("--config", type=Path, default=_default_config_path())
    parser.add_argument("--no-tray", action="store_true", help="Ejecuta solo el servidor HTTP, sin bandeja de Windows.")
    arguments = parser.parse_args()
    configuration = load_configuration(arguments.config)
    application = create_app(configuration)
    if platform.system() == "Windows" and not arguments.no_tray:
        start_server_with_tray(uvicorn, application, configuration.host, configuration.port, application.state.admin_url, __version__)
    else:
        uvicorn.run(application, host=configuration.host, port=configuration.port, log_level="info")


def _default_config_path() -> Path:
    if getattr(sys, "frozen", False):
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return program_data / "PuenteEscaner" / "config.yaml"
    return Path("config.yaml")


if __name__ == "__main__":
    main()
