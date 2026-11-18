from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from devicebridge import __version__
from devicebridge.config import AgentConfiguration
from devicebridge.devices.connections.virtualhere import AgentConnectionRegistry, VirtualHereClient, VirtualHereError, VirtualHereState
from devicebridge.devices.scanners.base import ScanRequest, ScannerDriver
from devicebridge.devices.scanners.discovery import discover_scanners
from devicebridge.devices.scanners.simulated import SimulatedScannerDriver, UnsupportedScanOption
from devicebridge.devices.scanners.twain import TwainScannerDriver
from devicebridge.devices.scanners.twain import TwainScanError
from devicebridge.devices.scanners.unavailable import ScannerDriverUnavailable, UnavailableScannerDriver
from devicebridge.devices.scanners.wia import WiaScannerDriver
from devicebridge.devices.scanners.wia import WiaScanError
from devicebridge.jobs.models import JobState
from devicebridge.jobs.repository import SQLiteJobRepository
from devicebridge.storage.files import TemporaryFileStore


logger = logging.getLogger(__name__)


class ScanBody(BaseModel):
    scanner_id: str = Field(min_length=1, max_length=128)
    source: str | None = Field(default=None, pattern="^(flatbed|adf)$")
    color_mode: str | None = Field(default=None, pattern="^(color|grayscale|black_and_white)$")
    resolution: int | None = Field(default=None, ge=75, le=1200)
    output_format: str | None = Field(default=None, pattern="^(png|jpeg|pdf)$")
    duplex: bool | None = None


def create_app(configuration: AgentConfiguration) -> FastAPI:
    token = os.environ.get(configuration.api_token_environment)
    if configuration.authentication_required and not token:
        raise RuntimeError(f"Falta la variable de entorno {configuration.api_token_environment}.")

    repository = SQLiteJobRepository(configuration.data_directory / "jobs.sqlite3")
    file_store = TemporaryFileStore(configuration.temporary_directory)
    drivers = _create_drivers(configuration)
    scanner_configuration = {scanner.identifier: scanner for scanner in configuration.scanners}
    virtualhere = (VirtualHereClient(configuration.virtualhere.executable_path, configuration.virtualhere.timeout_seconds)
                   if configuration.virtualhere else None)
    virtualhere_devices = ({device.identifier: device for device in configuration.virtualhere.devices}
                           if configuration.virtualhere else {})
    agent_connections = AgentConnectionRegistry()

    app = FastAPI(title="DeviceBridge Agent", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configuration.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def validate_local_request(request: Request, call_next):
        host = request.headers.get("host", "").split(":", 1)[0]
        if host not in {"127.0.0.1", "localhost"}:
            return _error(400, "HOST_NOT_ALLOWED", "Host no autorizado.")
        origin = request.headers.get("origin")
        if request.method != "OPTIONS" and origin not in configuration.allowed_origins:
            return _error(403, "ORIGIN_NOT_ALLOWED", "Origen no autorizado.")
        return await call_next(request)

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        if not configuration.authentication_required:
            return
        if not authorization or not authorization.startswith("Bearer "):
            raise _http_error(401, "AUTHORIZATION_REQUIRED", "Se requiere un token de autorización.")
        candidate = authorization.removeprefix("Bearer ")
        if not hmac.compare_digest(candidate, token):
            raise _http_error(403, "AUTHORIZATION_INVALID", "Token de autorización inválido.")

    Authorized = Annotated[None, Depends(authorize)]

    @app.get("/api/v1/health", dependencies=[Depends(authorize)])
    def health() -> dict[str, str]:
        return {"status": "ok", "installationId": configuration.installation_id}

    @app.get("/api/v1/version", dependencies=[Depends(authorize)])
    def version() -> dict[str, str]:
        return {"version": __version__}

    @app.get("/api/v1/scanners", dependencies=[Depends(authorize)])
    def scanners() -> dict[str, list[dict[str, object]]]:
        return {"items": [{"id": driver.identifier, "name": driver.display_name,
                           "defaults": _scan_defaults(scanner_configuration[driver.identifier]),
                           "capabilities": driver.capabilities().to_api()}
                          for driver in drivers.values()]}

    @app.get("/api/v1/scanners/detected", dependencies=[Depends(authorize)])
    def detected_scanners() -> dict[str, object]:
        detected, diagnostics = discover_scanners()
        configured = []
        for scanner in configuration.scanners:
            matches = [device for device in detected if _matches_configured_scanner(scanner, device)]
            configured.append({
                "id": scanner.identifier,
                "driver": scanner.driver,
                "detected": bool(matches),
                "matches": [{"technology": device.technology, "name": device.name, "id": device.identifier}
                            for device in matches],
            })
        return {
            "devices": [{"technology": device.technology, "name": device.name, "id": device.identifier}
                        for device in detected],
            "configured": configured,
            "diagnostics": diagnostics,
        }

    @app.get("/api/v1/scanners/{scanner_id}/capabilities", dependencies=[Depends(authorize)])
    def scanner_capabilities(scanner_id: str) -> dict[str, object]:
        driver = _driver_or_404(drivers, scanner_id)
        return {"scannerId": scanner_id, **driver.capabilities().to_api()}

    @app.get("/api/v1/virtualhere/devices", dependencies=[Depends(authorize)])
    def virtualhere_device_list() -> dict[str, list[dict[str, object]]]:
        client = _virtualhere_or_503(virtualhere)
        items = []
        for device in virtualhere_devices.values():
            try:
                status = client.get_device_status(device.address)
            except VirtualHereError as error:
                status = {"address": device.address, "state": VirtualHereState.ERROR, "detail": str(error)}
            else:
                status = status.to_api()
            items.append({"id": device.identifier, "name": device.display_name, "status": status})
        return {"items": items}

    @app.get("/api/v1/virtualhere/devices/{device_id}", dependencies=[Depends(authorize)])
    def virtualhere_device_status(device_id: str) -> dict[str, object]:
        client = _virtualhere_or_503(virtualhere)
        device = _virtualhere_device_or_404(virtualhere_devices, device_id)
        try:
            status = client.get_device_status(device.address)
        except VirtualHereError as error:
            raise _http_error(503, "VIRTUALHERE_UNAVAILABLE", str(error)) from error
        return {"id": device.identifier, "name": device.display_name, "status": status.to_api()}

    @app.post("/api/v1/virtualhere/devices/{device_id}/connect", dependencies=[Depends(authorize)])
    def virtualhere_connect(device_id: str) -> dict[str, object]:
        client = _virtualhere_or_503(virtualhere)
        device = _virtualhere_device_or_404(virtualhere_devices, device_id)
        try:
            before = client.get_device_status(device.address)
            if before.state == VirtualHereState.IN_USE_REMOTE:
                raise _http_error(409, "DEVICE_IN_USE_REMOTE", "El dispositivo está en uso por otro cliente.")
            after = client.connect(device.address)
        except VirtualHereError as error:
            raise _http_error(503, "VIRTUALHERE_CONNECT_FAILED", str(error)) from error
        confirmed_local = after.state == VirtualHereState.CONNECTED_LOCAL
        if confirmed_local:
            agent_connections.mark_connected(device.address)
        return {
            "id": device.identifier,
            "name": device.display_name,
            "status": after.to_api(),
            "connectionAccepted": True,
            "safeToDisconnect": confirmed_local,
        }

    @app.post("/api/v1/virtualhere/devices/{device_id}/disconnect", dependencies=[Depends(authorize)])
    def virtualhere_disconnect(device_id: str) -> dict[str, object]:
        client = _virtualhere_or_503(virtualhere)
        device = _virtualhere_device_or_404(virtualhere_devices, device_id)
        if not agent_connections.owns(device.address):
            raise _http_error(409, "DEVICE_NOT_OWNED_BY_AGENT",
                              "El agente no creó esta conexión durante la sesión actual; no se desconectará.")
        try:
            before = client.get_device_status(device.address)
            if before.state != VirtualHereState.CONNECTED_LOCAL:
                raise _http_error(409, "CONNECTION_STATE_UNCERTAIN",
                                  "No se pudo confirmar que la conexión siga siendo local; no se desconectará.")
            after = client.disconnect(device.address)
        except VirtualHereError as error:
            raise _http_error(503, "VIRTUALHERE_DISCONNECT_FAILED", str(error)) from error
        agent_connections.release(device.address)
        return {"id": device.identifier, "name": device.display_name, "status": after.to_api()}

    @app.post("/api/v1/scans", status_code=202, dependencies=[Depends(authorize)])
    def create_scan(body: ScanBody, background_tasks: BackgroundTasks,
                    idempotency_key: Annotated[str | None, Header()] = None) -> dict[str, object]:
        if not idempotency_key or len(idempotency_key) > 128:
            raise _http_error(400, "IDEMPOTENCY_KEY_REQUIRED", "Se requiere Idempotency-Key de hasta 128 caracteres.")
        driver = _driver_or_404(drivers, body.scanner_id)
        try:
            job = repository.create_or_get("scan", body.scanner_id, idempotency_key)
        except ValueError as error:
            raise _http_error(409, "IDEMPOTENCY_KEY_CONFLICT", str(error)) from error
        if job.state == JobState.QUEUED:
            defaults = scanner_configuration[body.scanner_id]
            request = ScanRequest(
                body.source or defaults.default_source,
                body.color_mode or defaults.default_color_mode,
                body.resolution or defaults.default_resolution,
                body.output_format or defaults.default_output_format,
                defaults.default_duplex if body.duplex is None else body.duplex,
            )
            background_tasks.add_task(
                _run_scan, repository, file_store, driver, job.identifier, request, configuration.debug_errors
            )
        return job.to_api()

    @app.get("/api/v1/scans/{job_id}", dependencies=[Depends(authorize)])
    def scan_status(job_id: str) -> dict[str, object]:
        job = repository.get(job_id)
        if not job or job.job_type != "scan":
            raise _http_error(404, "JOB_NOT_FOUND", "Trabajo no encontrado.")
        return job.to_api()

    @app.get("/api/v1/scans/{job_id}/file", dependencies=[Depends(authorize)])
    def scan_file(job_id: str) -> FileResponse:
        job = repository.get(job_id)
        if not job or job.job_type != "scan":
            raise _http_error(404, "JOB_NOT_FOUND", "Trabajo no encontrado.")
        if job.state != JobState.COMPLETED or not job.file_path:
            raise _http_error(409, "FILE_NOT_READY", "El archivo aún no está disponible.")
        path = Path(job.file_path)
        if not path.is_file():
            raise _http_error(410, "FILE_EXPIRED", "El archivo temporal ya no está disponible.")
        return FileResponse(path, media_type=job.file_media_type, filename=path.name)

    return app


def _create_drivers(configuration: AgentConfiguration) -> dict[str, ScannerDriver]:
    drivers: dict[str, ScannerDriver] = {}
    for scanner in configuration.scanners:
        if scanner.driver == "simulated":
            drivers[scanner.identifier] = SimulatedScannerDriver(scanner.identifier, scanner.display_name)
        elif scanner.driver == "wia":
            drivers[scanner.identifier] = WiaScannerDriver(
                scanner.identifier, scanner.display_name, scanner.windows_device, scanner.default_source
            )
        elif scanner.driver == "twain":
            drivers[scanner.identifier] = TwainScannerDriver(
                scanner.identifier, scanner.display_name, scanner.windows_device, scanner.default_source
            )
        else:
            drivers[scanner.identifier] = UnavailableScannerDriver(scanner.identifier, scanner.display_name, scanner.driver)
    return drivers


def _driver_or_404(drivers: dict[str, ScannerDriver], scanner_id: str) -> ScannerDriver:
    driver = drivers.get(scanner_id)
    if not driver:
        raise _http_error(404, "SCANNER_NOT_FOUND", "Escáner no configurado.")
    return driver


def _virtualhere_or_503(client: VirtualHereClient | None) -> VirtualHereClient:
    if not client:
        raise _http_error(503, "VIRTUALHERE_NOT_CONFIGURED", "VirtualHere no está configurado en este agente.")
    return client


def _virtualhere_device_or_404(devices, device_id: str):
    device = devices.get(device_id)
    if not device:
        raise _http_error(404, "VIRTUALHERE_DEVICE_NOT_FOUND", "Dispositivo VirtualHere no configurado.")
    return device


def _scan_defaults(scanner) -> dict[str, object]:
    return {
        "source": scanner.default_source,
        "colorMode": scanner.default_color_mode,
        "resolution": scanner.default_resolution,
        "outputFormat": scanner.default_output_format,
        "duplex": scanner.default_duplex,
    }


def _matches_configured_scanner(scanner, device) -> bool:
    if scanner.driver not in {"wia", "twain"} or device.technology.casefold() != scanner.driver:
        return False
    expected = scanner.windows_device.casefold()
    return expected in device.name.casefold() or expected == device.identifier.casefold()


def _run_scan(repository: SQLiteJobRepository, store: TemporaryFileStore, driver: ScannerDriver, job_id: str,
              request: ScanRequest, debug_errors: bool = False) -> None:
    repository.update(job_id, JobState.PROCESSING)
    try:
        result = driver.scan(request)
        path = store.write(job_id, result.filename_extension, result.content)
        repository.update(job_id, JobState.COMPLETED, file_path=str(path), file_media_type=result.media_type)
    except UnsupportedScanOption as error:
        repository.update(job_id, JobState.FAILED, error_code=str(error), error_message="Opción no compatible.")
    except ScannerDriverUnavailable as error:
        repository.update(job_id, JobState.FAILED, error_code="SCANNER_DRIVER_UNAVAILABLE",
                          error_message=f"No se pudo usar el escáner: {error}.")
    except (TwainScanError, WiaScanError) as error:
        repository.update(job_id, JobState.FAILED, error_code="SCAN_FAILED", error_message=str(error))
    except Exception:
        logger.exception("Error inesperado al procesar el escaneo %s.", job_id)
        message = "Error interno de escaneo."
        if debug_errors:
            import sys
            error = sys.exception()
            message = f"{type(error).__name__}: {error}"
        repository.update(job_id, JobState.FAILED, error_code="SCAN_FAILED", error_message=message)


def _http_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _error(status: int, code: str, message: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message}})
