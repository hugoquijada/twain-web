from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from devicebridge import __version__
from devicebridge.config import AgentConfiguration
from devicebridge.devices.scanners.base import ScanRequest, ScannerDriver
from devicebridge.devices.scanners.simulated import SimulatedScannerDriver, UnsupportedScanOption
from devicebridge.devices.scanners.unavailable import ScannerDriverUnavailable, UnavailableScannerDriver
from devicebridge.jobs.models import JobState
from devicebridge.jobs.repository import SQLiteJobRepository
from devicebridge.storage.files import TemporaryFileStore


class ScanBody(BaseModel):
    scanner_id: str = Field(min_length=1, max_length=128)
    source: str = Field(default="adf", pattern="^(flatbed|adf)$")
    color_mode: str = Field(default="color", pattern="^(color|grayscale|black_and_white)$")
    resolution: int = Field(default=300, ge=75, le=1200)
    output_format: str = Field(default="png", pattern="^(png|jpeg|pdf)$")
    duplex: bool = False


def create_app(configuration: AgentConfiguration) -> FastAPI:
    token = os.environ.get(configuration.api_token_environment)
    if not token:
        raise RuntimeError(f"Falta la variable de entorno {configuration.api_token_environment}.")

    repository = SQLiteJobRepository(configuration.data_directory / "jobs.sqlite3")
    file_store = TemporaryFileStore(configuration.temporary_directory)
    drivers = _create_drivers(configuration)

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
        return {"items": [{"id": driver.identifier, "name": driver.display_name, "capabilities": driver.capabilities().to_api()}
                          for driver in drivers.values()]}

    @app.get("/api/v1/scanners/{scanner_id}/capabilities", dependencies=[Depends(authorize)])
    def scanner_capabilities(scanner_id: str) -> dict[str, object]:
        driver = _driver_or_404(drivers, scanner_id)
        return {"scannerId": scanner_id, **driver.capabilities().to_api()}

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
            request = ScanRequest(body.source, body.color_mode, body.resolution, body.output_format, body.duplex)
            background_tasks.add_task(_run_scan, repository, file_store, driver, job.identifier, request)
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
        else:
            drivers[scanner.identifier] = UnavailableScannerDriver(scanner.identifier, scanner.display_name, scanner.driver)
    return drivers


def _driver_or_404(drivers: dict[str, ScannerDriver], scanner_id: str) -> ScannerDriver:
    driver = drivers.get(scanner_id)
    if not driver:
        raise _http_error(404, "SCANNER_NOT_FOUND", "Escáner no configurado.")
    return driver


def _run_scan(repository: SQLiteJobRepository, store: TemporaryFileStore, driver: ScannerDriver, job_id: str,
              request: ScanRequest) -> None:
    repository.update(job_id, JobState.PROCESSING)
    try:
        result = driver.scan(request)
        path = store.write(job_id, result.filename_extension, result.content)
        repository.update(job_id, JobState.COMPLETED, file_path=str(path), file_media_type=result.media_type)
    except UnsupportedScanOption as error:
        repository.update(job_id, JobState.FAILED, error_code=str(error), error_message="Opción no compatible.")
    except ScannerDriverUnavailable as error:
        repository.update(job_id, JobState.FAILED, error_code="SCANNER_DRIVER_UNAVAILABLE",
                          error_message=f"El adaptador {error} no está implementado o validado.")
    except Exception:
        repository.update(job_id, JobState.FAILED, error_code="SCAN_FAILED", error_message="Error interno de escaneo.")


def _http_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _error(status: int, code: str, message: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message}})
