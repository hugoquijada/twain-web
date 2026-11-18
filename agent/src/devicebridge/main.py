from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from devicebridge.api.app import create_app
from devicebridge.config import load_configuration


def main() -> None:
    parser = argparse.ArgumentParser(description="DeviceBridge local agent")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    arguments = parser.parse_args()
    configuration = load_configuration(arguments.config)
    uvicorn.run(create_app(configuration), host=configuration.host, port=configuration.port, log_level="info")


if __name__ == "__main__":
    main()
