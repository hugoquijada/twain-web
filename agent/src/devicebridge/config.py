from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml


class ConfigurationError(ValueError):
    """Raised when config.yaml is unsafe or incomplete."""


@dataclass(frozen=True)
class ScannerConfiguration:
    identifier: str
    display_name: str
    driver: str
    windows_device: str
    default_source: str
    default_color_mode: str
    default_resolution: int
    default_output_format: str
    default_duplex: bool


@dataclass(frozen=True)
class VirtualHereDeviceConfiguration:
    identifier: str
    display_name: str
    address: str


@dataclass(frozen=True)
class VirtualHereConfiguration:
    executable_path: Path
    timeout_seconds: int
    devices: tuple[VirtualHereDeviceConfiguration, ...]


@dataclass(frozen=True)
class AgentConfiguration:
    installation_id: str
    host: str
    port: int
    data_directory: Path
    temporary_directory: Path
    retention_hours: int
    allowed_origins: tuple[str, ...]
    api_token_environment: str
    authentication_required: bool
    scanners: tuple[ScannerConfiguration, ...]
    virtualhere: VirtualHereConfiguration | None


def load_configuration(path: Path) -> AgentConfiguration:
    with path.open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}

    agent = raw.get("agent")
    if not isinstance(agent, dict):
        raise ConfigurationError("Se requiere la sección agent.")

    host = agent.get("host")
    if host != "127.0.0.1":
        raise ConfigurationError("agent.host debe ser exactamente 127.0.0.1.")

    port = agent.get("port", 8765)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigurationError("agent.port debe ser un puerto válido.")

    origins = agent.get("allowed_origins")
    if not isinstance(origins, list) or not origins:
        raise ConfigurationError("agent.allowed_origins debe contener al menos un origen explícito.")
    normalized_origins = tuple(_validate_origin(origin) for origin in origins)

    token_environment = agent.get("api_token_environment")
    if not isinstance(token_environment, str) or not token_environment.isidentifier():
        raise ConfigurationError("agent.api_token_environment debe ser un nombre de variable de entorno.")

    authentication_required = agent.get("authentication_required", True)
    if not isinstance(authentication_required, bool):
        raise ConfigurationError("agent.authentication_required debe ser true o false.")

    scanners = tuple(_load_scanner(item) for item in raw.get("scanners", []))
    identifiers = [scanner.identifier for scanner in scanners]
    if len(identifiers) != len(set(identifiers)):
        raise ConfigurationError("Los identificadores de escáner deben ser únicos.")
    virtualhere = _load_virtualhere(raw.get("virtualhere"))

    return AgentConfiguration(
        installation_id=_required_string(agent, "installation_id"),
        host=host,
        port=port,
        data_directory=Path(_required_string(agent, "data_directory")).expanduser(),
        temporary_directory=Path(_required_string(agent, "temporary_directory")).expanduser(),
        retention_hours=_positive_integer(agent, "retention_hours"),
        allowed_origins=normalized_origins,
        api_token_environment=token_environment,
        authentication_required=authentication_required,
        scanners=scanners,
        virtualhere=virtualhere,
    )


def _load_scanner(raw: object) -> ScannerConfiguration:
    if not isinstance(raw, dict):
        raise ConfigurationError("Cada escáner debe ser un objeto.")
    driver = _required_string(raw, "driver").lower()
    if driver not in {"simulated", "wia", "twain"}:
        raise ConfigurationError("scanner.driver debe ser simulated, wia o twain.")
    source = raw.get("default_source", "flatbed")
    if source not in {"flatbed", "adf"}:
        raise ConfigurationError("scanner.default_source debe ser flatbed o adf.")
    color_mode = raw.get("default_color_mode", "color")
    if color_mode not in {"color", "grayscale", "black_and_white"}:
        raise ConfigurationError("scanner.default_color_mode no es válido.")
    resolution = raw.get("default_resolution", 300)
    if not isinstance(resolution, int) or resolution not in {75, 100, 150, 200, 300, 600, 1200}:
        raise ConfigurationError("scanner.default_resolution no es válido.")
    output_format = raw.get("default_output_format", "pdf")
    if output_format not in {"png", "jpeg", "pdf"}:
        raise ConfigurationError("scanner.default_output_format no es válido.")
    duplex = raw.get("default_duplex", False)
    if not isinstance(duplex, bool):
        raise ConfigurationError("scanner.default_duplex debe ser true o false.")
    return ScannerConfiguration(
        identifier=_required_string(raw, "id"),
        display_name=_required_string(raw, "display_name"),
        driver=driver,
        windows_device=_required_string(raw, "windows_device"),
        default_source=source,
        default_color_mode=color_mode,
        default_resolution=resolution,
        default_output_format=output_format,
        default_duplex=duplex,
    )


def _load_virtualhere(raw: object) -> VirtualHereConfiguration | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigurationError("virtualhere debe ser un objeto.")
    devices = tuple(_load_virtualhere_device(item) for item in raw.get("devices", []))
    identifiers = [device.identifier for device in devices]
    if len(identifiers) != len(set(identifiers)):
        raise ConfigurationError("Los identificadores de VirtualHere deben ser únicos.")
    return VirtualHereConfiguration(
        executable_path=Path(_required_string(raw, "executable_path")).expanduser(),
        timeout_seconds=_positive_integer(raw, "timeout_seconds"),
        devices=devices,
    )


def _load_virtualhere_device(raw: object) -> VirtualHereDeviceConfiguration:
    if not isinstance(raw, dict):
        raise ConfigurationError("Cada dispositivo VirtualHere debe ser un objeto.")
    address = _required_string(raw, "address")
    if "," in address or "\n" in address or "\r" in address:
        raise ConfigurationError("La dirección VirtualHere contiene caracteres no permitidos.")
    return VirtualHereDeviceConfiguration(
        identifier=_required_string(raw, "id"),
        display_name=_required_string(raw, "display_name"),
        address=address,
    )


def _validate_origin(value: object) -> str:
    if not isinstance(value, str):
        raise ConfigurationError("Cada origen permitido debe ser texto.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
        raise ConfigurationError(f"Origen permitido inválido: {value!r}")
    return value.rstrip("/")


def _required_string(values: dict, key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"Se requiere {key}.")
    return value.strip()


def _positive_integer(values: dict, key: str) -> int:
    value = values.get(key)
    if not isinstance(value, int) or value <= 0:
        raise ConfigurationError(f"{key} debe ser un entero positivo.")
    return value
