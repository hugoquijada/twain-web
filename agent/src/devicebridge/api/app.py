from __future__ import annotations

import hmac
import logging
import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from devicebridge import __version__
from devicebridge.config import AgentConfiguration, ScannerConfiguration
from devicebridge.devices.connections.virtualhere import AgentConnectionRegistry, VirtualHereClient, VirtualHereError, VirtualHereState
from devicebridge.devices.scanners.base import ScanRequest, ScannerDriver
from devicebridge.devices.scanners.discovery import discover_scanners
from devicebridge.devices.scanners.registry import ScannerRegistry
from devicebridge.devices.scanners.simulated import SimulatedScannerDriver
from devicebridge.devices.scanners.twain import TwainScannerDriver
from devicebridge.devices.scanners.unavailable import ScannerDriverUnavailable, UnavailableScannerDriver
from devicebridge.devices.scanners.wia import WiaScannerDriver
from devicebridge.jobs.models import JobState
from devicebridge.jobs.repository import JobInProgressError, SQLiteJobRepository
from devicebridge.jobs.scan_manager import ScanJobManager
from devicebridge.storage.files import TemporaryFileStore
from devicebridge.storage.scanner_profiles import ScannerProfileRepository


logger = logging.getLogger(__name__)


class ScanBody(BaseModel):
    scanner_id: str = Field(min_length=1, max_length=128)
    source: str | None = Field(default=None, pattern="^(flatbed|adf)$")
    color_mode: str | None = Field(default=None, pattern="^(color|grayscale|black_and_white)$")
    resolution: int | None = Field(default=None, ge=75, le=1200)
    output_format: str | None = Field(default=None, pattern="^(png|jpeg|pdf)$")
    duplex: bool | None = None


class AdminScannerProfileBody(BaseModel):
    id: str = Field(pattern="^[a-z0-9-]{1,64}$")
    display_name: str = Field(min_length=1, max_length=200)
    driver: str = Field(pattern="^(twain|wia)$")
    windows_device: str = Field(min_length=1, max_length=300)
    default_source: str = Field(default="flatbed", pattern="^(flatbed|adf)$")
    default_color_mode: str = Field(default="color", pattern="^(color|grayscale|black_and_white)$")
    default_resolution: int = Field(default=300, ge=75, le=1200)
    default_output_format: str = Field(default="jpeg", pattern="^(png|jpeg|pdf)$")
    default_duplex: bool = False


def create_app(configuration: AgentConfiguration) -> FastAPI:
    token = os.environ.get(configuration.api_token_environment)
    if configuration.authentication_required and not token:
        raise RuntimeError(f"Falta la variable de entorno {configuration.api_token_environment}.")

    repository = SQLiteJobRepository(configuration.data_directory / "jobs.sqlite3")
    file_store = TemporaryFileStore(configuration.temporary_directory)
    scan_jobs = ScanJobManager(repository, file_store, configuration.debug_errors)
    scanner_profiles = ScannerProfileRepository(configuration.data_directory / "devicebridge.sqlite3")
    scanner_profiles.seed_if_empty(configuration.scanners)
    scanner_registry = ScannerRegistry(scanner_profiles)
    virtualhere = (VirtualHereClient(configuration.virtualhere.executable_path, configuration.virtualhere.timeout_seconds)
                   if configuration.virtualhere else None)
    virtualhere_devices = ({device.identifier: device for device in configuration.virtualhere.devices}
                           if configuration.virtualhere else {})
    agent_connections = AgentConnectionRegistry()

    app = FastAPI(
        title="Puente Escáner API",
        version=__version__,
        description="API local para que una aplicación web autorizada use perfiles de escáner de Windows.",
        docs_url=None,
        redoc_url=None,
        openapi_tags=[
            {"name": "Escáner · 1. Detectar", "description": "Comprueba los perfiles y fuentes disponibles."},
            {"name": "Escáner · 2. Consultar", "description": "Consulta capacidades antes de solicitar una captura."},
            {"name": "Escáner · 3. Iniciar", "description": "Crea un trabajo de escaneo."},
            {"name": "Escáner · 4. Seguimiento", "description": "Consulta el estado hasta completarse o fallar."},
            {"name": "Escáner · 5. Archivo", "description": "Descarga el resultado del trabajo terminado."},
            {"name": "VirtualHere", "description": "Administra dispositivos USB configurados para VirtualHere."},
        ],
    )
    app.state.admin_token = scanner_profiles.admin_token()
    app.state.admin_url = f"http://127.0.0.1:{configuration.port}/admin#token={app.state.admin_token}"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configuration.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def validate_local_request(request: Request, call_next):
        host = request.headers.get("host", "").split(":", 1)[0]
        if host not in {"127.0.0.1", "localhost"}:
            return _error(400, "HOST_NOT_ALLOWED", "Host no autorizado.")
        origin = request.headers.get("origin")
        admin_request = request.url.path.startswith("/admin")
        documentation_request = request.url.path in {"/docs", "/openapi.json"}
        local_admin_origin = f"http://127.0.0.1:{configuration.port}"
        if (admin_request or documentation_request) and origin and origin != local_admin_origin:
            return _error(403, "ORIGIN_NOT_ALLOWED", "Origen administrativo no autorizado.")
        public_local_request = origin == local_admin_origin
        if (not admin_request and not documentation_request and request.method != "OPTIONS"
                and not public_local_request and origin not in configuration.allowed_origins):
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

    def authorize_admin(x_devicebridge_admin: Annotated[str | None, Header()] = None) -> None:
        if not x_devicebridge_admin or not hmac.compare_digest(x_devicebridge_admin, app.state.admin_token):
            raise _http_error(403, "ADMIN_AUTHORIZATION_INVALID", "Sesión administrativa no autorizada.")

    Authorized = Annotated[None, Depends(authorize)]

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page() -> str:
        return _ADMIN_PAGE.replace("__APP_VERSION__", __version__)

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    def api_documentation() -> str:
        return _SCALAR_PAGE

    @app.get("/admin/api/scanners", dependencies=[Depends(authorize_admin)])
    def admin_scanners() -> dict[str, object]:
        detected, diagnostics = discover_scanners()
        profiles, _ = scanner_registry.snapshot()
        return {
            "detected": [{"technology": item.technology, "name": item.name, "id": item.identifier} for item in detected],
            "profiles": [_profile_to_api(profile) for profile in profiles.values()],
            "diagnostics": diagnostics,
        }

    @app.post("/admin/api/scanners", dependencies=[Depends(authorize_admin)])
    def save_admin_scanner(body: AdminScannerProfileBody) -> dict[str, object]:
        profile = ScannerConfiguration(
            body.id, body.display_name, body.driver, body.windows_device, body.default_source,
            body.default_color_mode, body.default_resolution, body.default_output_format, body.default_duplex,
        )
        scanner_profiles.upsert(profile)
        scanner_registry.refresh()
        return _profile_to_api(profile)

    @app.delete("/admin/api/scanners/{scanner_id}", status_code=204, dependencies=[Depends(authorize_admin)])
    def delete_admin_scanner(scanner_id: str) -> None:
        if not scanner_profiles.delete(scanner_id):
            raise _http_error(404, "SCANNER_PROFILE_NOT_FOUND", "Perfil no encontrado.")
        scanner_registry.refresh()

    @app.post("/admin/api/scanners/{scanner_id}/test", status_code=202, dependencies=[Depends(authorize_admin)])
    def test_admin_scanner(scanner_id: str) -> dict[str, object]:
        scanner_configuration, drivers = scanner_registry.snapshot()
        driver = _driver_or_404(drivers, scanner_id)
        profile = scanner_configuration[scanner_id]
        try:
            job = repository.create_or_get_exclusive("scan", scanner_id, f"admin-test-{uuid.uuid4()}")
        except JobInProgressError as error:
            raise _http_error(409, "SCAN_IN_PROGRESS", "Ya hay una captura activa para este escáner.") from error
        request = ScanRequest(profile.default_source, profile.default_color_mode, profile.default_resolution,
                              profile.default_output_format, profile.default_duplex)
        scan_jobs.enqueue(job, driver, request)
        return job.to_api()

    @app.get("/admin/api/scans/{job_id}", dependencies=[Depends(authorize_admin)])
    def admin_scan_status(job_id: str) -> dict[str, object]:
        job = repository.get(job_id)
        if not job or job.job_type != "scan":
            raise _http_error(404, "JOB_NOT_FOUND", "Prueba no encontrada.")
        return job.to_api()

    @app.get("/admin/api/scans/{job_id}/file", dependencies=[Depends(authorize_admin)])
    def admin_scan_file(job_id: str) -> FileResponse:
        return _scan_file_response(repository, job_id)

    @app.get("/api/v1/health", dependencies=[Depends(authorize)])
    def health() -> dict[str, str]:
        return {"status": "ok", "installationId": configuration.installation_id}

    @app.get("/api/v1/version", dependencies=[Depends(authorize)])
    def version() -> dict[str, str]:
        return {"version": __version__}

    @app.get("/api/v1/scanners", dependencies=[Depends(authorize)], tags=["Escáner · 1. Detectar"])
    def scanners() -> dict[str, list[dict[str, object]]]:
        scanner_configuration, drivers = scanner_registry.snapshot()
        return {"items": [{"id": driver.identifier, "name": driver.display_name,
                           "defaults": _scan_defaults(scanner_configuration[driver.identifier]),
                           "capabilities": driver.capabilities().to_api()}
                          for driver in drivers.values()]}

    @app.get("/api/v1/scanners/detected", dependencies=[Depends(authorize)], tags=["Escáner · 1. Detectar"])
    def detected_scanners() -> dict[str, object]:
        detected, diagnostics = discover_scanners()
        scanner_configuration, _ = scanner_registry.snapshot()
        configured = []
        for scanner in scanner_configuration.values():
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

    @app.get("/api/v1/scanners/{scanner_id}/capabilities", dependencies=[Depends(authorize)], tags=["Escáner · 2. Consultar"])
    def scanner_capabilities(scanner_id: str) -> dict[str, object]:
        _, drivers = scanner_registry.snapshot()
        driver = _driver_or_404(drivers, scanner_id)
        return {"scannerId": scanner_id, **driver.capabilities().to_api()}

    @app.get("/api/v1/virtualhere/devices", dependencies=[Depends(authorize)], tags=["VirtualHere"])
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

    @app.get("/api/v1/virtualhere/devices/{device_id}", dependencies=[Depends(authorize)], tags=["VirtualHere"])
    def virtualhere_device_status(device_id: str) -> dict[str, object]:
        client = _virtualhere_or_503(virtualhere)
        device = _virtualhere_device_or_404(virtualhere_devices, device_id)
        try:
            status = client.get_device_status(device.address)
        except VirtualHereError as error:
            raise _http_error(503, "VIRTUALHERE_UNAVAILABLE", str(error)) from error
        return {"id": device.identifier, "name": device.display_name, "status": status.to_api()}

    @app.post("/api/v1/virtualhere/devices/{device_id}/connect", dependencies=[Depends(authorize)], tags=["VirtualHere"])
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

    @app.post("/api/v1/virtualhere/devices/{device_id}/disconnect", dependencies=[Depends(authorize)], tags=["VirtualHere"])
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

    @app.post("/api/v1/scans", status_code=202, dependencies=[Depends(authorize)], tags=["Escáner · 3. Iniciar"])
    def create_scan(body: ScanBody,
                    idempotency_key: Annotated[str | None, Header()] = None) -> dict[str, object]:
        if not idempotency_key or len(idempotency_key) > 128:
            raise _http_error(400, "IDEMPOTENCY_KEY_REQUIRED", "Se requiere Idempotency-Key de hasta 128 caracteres.")
        scanner_configuration, drivers = scanner_registry.snapshot()
        driver = _driver_or_404(drivers, body.scanner_id)
        try:
            job = repository.create_or_get_exclusive("scan", body.scanner_id, idempotency_key)
        except ValueError as error:
            raise _http_error(409, "IDEMPOTENCY_KEY_CONFLICT", str(error)) from error
        except JobInProgressError as error:
            raise _http_error(409, "SCAN_IN_PROGRESS",
                              f"El escáner ya está ocupado por el trabajo {error.job.identifier}.") from error
        if job.state == JobState.QUEUED:
            defaults = scanner_configuration[body.scanner_id]
            request = ScanRequest(
                body.source or defaults.default_source,
                body.color_mode or defaults.default_color_mode,
                body.resolution or defaults.default_resolution,
                body.output_format or defaults.default_output_format,
                defaults.default_duplex if body.duplex is None else body.duplex,
            )
            scan_jobs.enqueue(job, driver, request)
        return job.to_api()

    @app.get("/api/v1/scans/{job_id}", dependencies=[Depends(authorize)], tags=["Escáner · 4. Seguimiento"])
    def scan_status(job_id: str) -> dict[str, object]:
        job = repository.get(job_id)
        if not job or job.job_type != "scan":
            raise _http_error(404, "JOB_NOT_FOUND", "Trabajo no encontrado.")
        return job.to_api()

    @app.post("/api/v1/scans/{job_id}/cancel", dependencies=[Depends(authorize)], tags=["Escáner · 4. Seguimiento"])
    def cancel_scan(job_id: str) -> dict[str, object]:
        try:
            return scan_jobs.cancel(job_id).to_api()
        except KeyError as error:
            raise _http_error(404, "JOB_NOT_FOUND", "Trabajo no encontrado.") from error

    @app.get("/api/v1/jobs", dependencies=[Depends(authorize)], tags=["Escáner · 4. Seguimiento"])
    def list_jobs() -> dict[str, list[dict[str, object]]]:
        return {"items": [job.to_api() for job in repository.list(job_type="scan")]}

    @app.delete("/api/v1/jobs/{job_id}", status_code=204, dependencies=[Depends(authorize)], tags=["Escáner · 4. Seguimiento"])
    def delete_job(job_id: str) -> None:
        job = repository.get(job_id)
        if not job or job.job_type != "scan":
            raise _http_error(404, "JOB_NOT_FOUND", "Trabajo no encontrado.")
        if job.state in {JobState.QUEUED, JobState.PROCESSING, JobState.CANCEL_REQUESTED}:
            raise _http_error(409, "JOB_NOT_TERMINAL", "Cancele el trabajo y espere a que termine antes de eliminarlo.")
        if job.file_path:
            Path(job.file_path).unlink(missing_ok=True)
        repository.delete(job_id)

    @app.get("/api/v1/scans/{job_id}/file", dependencies=[Depends(authorize)], tags=["Escáner · 5. Archivo"])
    def scan_file(job_id: str) -> FileResponse:
        return _scan_file_response(repository, job_id)

    def custom_openapi() -> dict[str, object]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )
        schema["paths"] = {
            path: methods for path, methods in schema.get("paths", {}).items()
            if path.startswith("/api/v1/scanners")
            or path.startswith("/api/v1/scans")
            or path.startswith("/api/v1/jobs")
            or path.startswith("/api/v1/virtualhere")
        }
        components = schema.setdefault("components", {})
        components["securitySchemes"] = {
            "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "token"},
        }
        for path, methods in schema.get("paths", {}).items():
            for operation in methods.values():
                if isinstance(operation, dict):
                    operation.setdefault("security", [{"BearerAuth": []}])
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi
    return app


def _scan_file_response(repository: SQLiteJobRepository, job_id: str) -> FileResponse:
    job = repository.get(job_id)
    if not job or job.job_type != "scan":
        raise _http_error(404, "JOB_NOT_FOUND", "Trabajo no encontrado.")
    if job.state != JobState.COMPLETED or not job.file_path:
        raise _http_error(409, "FILE_NOT_READY", "El archivo aún no está disponible.")
    path = Path(job.file_path)
    if not path.is_file():
        raise _http_error(410, "FILE_EXPIRED", "El archivo temporal ya no está disponible.")
    return FileResponse(path, media_type=job.file_media_type, filename=path.name)


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


def _profile_to_api(profile: ScannerConfiguration) -> dict[str, object]:
    return {
        "id": profile.identifier, "displayName": profile.display_name, "driver": profile.driver,
        "windowsDevice": profile.windows_device, "defaults": _scan_defaults(profile),
    }


_ADMIN_PAGE = """<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Puente Escáner · Administración</title><script src='https://cdn.tailwindcss.com'></script><style>body{background:#f4efe6!important;color:#20313a!important}.bg-slate-950{background-color:#f4efe6!important}.text-slate-100{color:#20313a!important}[class~='bg-slate-900/70'],[class~='bg-slate-950/60']{background-color:#fffdf8!important}.border-slate-800{border-color:#d9d0c4!important}.bg-slate-800{background-color:#315d6c!important;color:#fff!important}.bg-slate-800:hover{background-color:#254a57!important}.bg-emerald-500{background-color:#0e6b7e!important;color:#fff!important}.bg-emerald-500:hover{background-color:#07576a!important}.text-slate-400,.text-slate-500,.text-slate-300{color:#61737b!important}[class~='bg-amber-950/40']{background-color:#fff5dc!important}[class~='border-amber-900/70']{border-color:#dfbc78!important}.text-amber-100{color:#6c4614!important}.border-rose-900{border-color:#bb6d61!important}.text-rose-300{color:#934238!important}[class~='hover:bg-rose-950']:hover{background-color:#fff0ed!important}</style></head>
<body class='min-h-screen bg-slate-950 text-slate-100'><main class='mx-auto max-w-5xl px-5 py-10'><header class='mb-8 flex items-center justify-between gap-4'><div><h1 class='text-3xl font-bold tracking-tight'>Puente Escáner</h1><p class='mt-1 text-sm text-slate-500'>Versión __APP_VERSION__</p></div><button id='refresh' class='rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium hover:bg-slate-700'>Actualizar</button></header>
<section class='mb-6 rounded-xl border border-slate-800 bg-slate-900/70 p-6 shadow-2xl'><div class='flex items-center justify-between gap-4'><h2 class='text-lg font-semibold'>Perfiles guardados</h2><button id='new-profile' class='rounded-lg bg-emerald-500 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-emerald-400'>Nuevo perfil</button></div><div id='profiles' class='mt-4 space-y-3'></div></section>
<section class='mb-6 rounded-xl border border-slate-800 bg-slate-900/70 p-6'><h2 class='text-lg font-semibold'>Buscar escáner</h2><div id='detected' class='mt-4 grid gap-3 md:grid-cols-2'></div></section>
<section id='profile-panel' class='hidden rounded-xl border border-slate-800 bg-slate-900/70 p-6'><h2 class='text-lg font-semibold'>Configuración del perfil</h2><form id='profile' class='mt-5 grid gap-4 sm:grid-cols-2'><label class='text-sm'>ID lógico<input name='id' required class='mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 outline-none focus:border-emerald-400'></label><label class='text-sm'>Nombre<input name='display_name' required class='mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 outline-none focus:border-emerald-400'></label><label class='text-sm'>Controlador<select name='driver' class='mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2'><option value='twain'>TWAIN</option><option value='wia'>WIA</option></select></label><label class='text-sm'>Fuente Windows<input name='windows_device' required class='mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 outline-none focus:border-emerald-400'></label><label class='text-sm'>Origen<select name='default_source' class='mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2'><option value='flatbed'>Cristal</option><option value='adf'>Bandeja</option></select></label><label class='text-sm'>Color<select name='default_color_mode' class='mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2'><option value='color'>Color</option><option value='grayscale'>Grises</option><option value='black_and_white'>Blanco y negro</option></select></label><label class='text-sm'>Resolución<select name='default_resolution' class='mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2'><option>150</option><option>200</option><option selected>300</option><option>600</option></select></label><label class='text-sm'>Formato<select name='default_output_format' class='mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2'><option>pdf</option><option>png</option><option selected>jpeg</option></select></label><label class='flex items-center gap-2 text-sm text-slate-300 sm:col-span-2'><input type='checkbox' name='default_duplex' class='h-4 w-4 accent-emerald-500'> Dúplex</label><button class='rounded-lg bg-emerald-500 px-4 py-2 font-semibold text-slate-950 hover:bg-emerald-400 sm:col-span-2'>Guardar perfil</button></form></section><pre id='status' class='mt-6 hidden whitespace-pre-wrap rounded-xl border border-amber-900/70 bg-amber-950/40 p-4 text-sm text-amber-100'></pre></main>
<script>
const token=new URLSearchParams(location.hash.slice(1)).get('token'),headers={'X-DeviceBridge-Admin':token},status=document.querySelector('#status'),form=document.querySelector('#profile');
const profilePanel=document.querySelector('#profile-panel');
const slug=s=>s.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/(^-|-$)/g,'').slice(0,64);
const message=value=>{status.textContent=value||'';status.classList.toggle('hidden',!value)};
const button=(text,classes)=>Object.assign(document.createElement('button'),{textContent:text,className:classes,type:'button'});
const showForm=()=>{profilePanel.classList.remove('hidden');profilePanel.scrollIntoView({behavior:'smooth',block:'start'})};
async function testProfile(id){message('Iniciando prueba…');const response=await fetch('/admin/api/scanners/'+encodeURIComponent(id)+'/test',{method:'POST',headers});if(!response.ok){message(await response.text());return}const job=await response.json();await pollTest(job.id)}
async function pollTest(jobId){for(;;){const response=await fetch('/admin/api/scans/'+encodeURIComponent(jobId),{headers});if(!response.ok){message(await response.text());return}const job=await response.json();message('Prueba: '+job.state);if(job.state==='COMPLETED'){const file=await fetch('/admin/api/scans/'+encodeURIComponent(job.id)+'/file',{headers});const blob=await file.blob();const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='prueba-'+job.id;link.textContent='Descargar resultado de prueba';link.className='mt-3 inline-block font-semibold text-emerald-300 underline';const content=[document.createTextNode('Prueba completada. '),link];if(blob.type.startsWith('image/')){const image=document.createElement('img');image.src=url;image.alt='Vista previa de la prueba';image.className='mt-4 max-h-80 rounded-lg border border-slate-700 bg-white';content.push(image)}status.replaceChildren(...content);status.classList.remove('hidden');return}if(['FAILED','CANCELLED','TIMEOUT','UNCERTAIN'].includes(job.state)){message(job.error?.message||job.state);return}await new Promise(resolve=>setTimeout(resolve,500))}}
async function load(){const r=await fetch('/admin/api/scanners',{headers});if(!r.ok)throw new Error('Sesión administrativa inválida. Abra esta página desde el icono de Puente Escáner.');const d=await r.json();const detected=document.querySelector('#detected');detected.replaceChildren(...d.detected.map(x=>{const card=document.createElement('article');card.className='flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950/60 p-4';const text=document.createElement('div');text.innerHTML='<p class="font-medium"></p><p class="mt-1 text-xs uppercase tracking-wider text-slate-500"></p>';text.children[0].textContent=x.name;text.children[1].textContent=x.technology;const use=button('Usar','shrink-0 rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400');use.onclick=()=>{form.elements.id.value=slug(x.name);form.elements.display_name.value=x.name;form.elements.driver.value=x.technology.toLowerCase();form.elements.windows_device.value=x.name;showForm()};card.append(text,use);return card}));if(!d.detected.length)detected.textContent='No se detectaron fuentes.';const profiles=document.querySelector('#profiles');profiles.replaceChildren(...d.profiles.map(x=>{const row=document.createElement('article');row.className='flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3';const text=document.createElement('div');text.innerHTML='<p class="font-medium"></p><p class="mt-1 text-xs text-slate-500"></p>';text.children[0].textContent=x.displayName;text.children[1].textContent=x.id+' · '+x.driver.toUpperCase();const actions=document.createElement('div');actions.className='flex gap-2';const test=button('Probar','rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400');test.onclick=()=>testProfile(x.id);const remove=button('Eliminar','rounded-md border border-rose-900 px-3 py-1.5 text-sm text-rose-300 hover:bg-rose-950');remove.onclick=async()=>{if(!confirm('¿Eliminar el perfil '+x.displayName+'?'))return;const response=await fetch('/admin/api/scanners/'+encodeURIComponent(x.id),{method:'DELETE',headers});if(!response.ok)message(await response.text());else{message('Perfil eliminado.');load()}};actions.append(test,remove);row.append(text,actions);return row}));if(!d.profiles.length)profiles.textContent='Aún no hay perfiles guardados.';message(d.diagnostics.join('\\n'))}
form.onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(form));d.default_resolution=Number(d.default_resolution);d.default_duplex=form.elements.default_duplex.checked;const r=await fetch('/admin/api/scanners',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(d)});if(!r.ok)message(await r.text());else{message('Perfil guardado.');profilePanel.classList.add('hidden');load()}};document.querySelector('#new-profile').onclick=()=>{form.reset();showForm()};document.querySelector('#refresh').onclick=()=>load().catch(e=>message(e.message));load().catch(e=>message(e.message));
</script></body></html>"""


_SCALAR_PAGE = """<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Puente Escáner · API</title></head><body><div id='app'></div><script src='https://cdn.jsdelivr.net/npm/@scalar/api-reference'></script><script>Scalar.createApiReference('#app',{url:'/openapi.json',pageTitle:'Puente Escáner · API',theme:'purple',layout:'modern',hideClientButton:false})</script></body></html>"""


def _http_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _error(status: int, code: str, message: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message}})
