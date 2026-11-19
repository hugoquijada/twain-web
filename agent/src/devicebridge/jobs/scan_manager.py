from __future__ import annotations

import logging
import sys
import threading

from devicebridge.devices.scanners.base import ScanRequest, ScannerDriver
from devicebridge.devices.scanners.simulated import UnsupportedScanOption
from devicebridge.devices.scanners.twain import TwainScanError
from devicebridge.devices.scanners.unavailable import ScannerDriverUnavailable
from devicebridge.devices.scanners.wia import WiaScanError
from devicebridge.storage.files import TemporaryFileStore

from .models import Job, JobState
from .repository import SQLiteJobRepository


logger = logging.getLogger(__name__)


class ScanJobManager:
    """Serializes captures by device and keeps queued work cancellable."""

    def __init__(self, repository: SQLiteJobRepository, file_store: TemporaryFileStore, debug_errors: bool):
        self._repository = repository
        self._file_store = file_store
        self._debug_errors = debug_errors
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._scheduled: set[str] = set()
        self._scheduled_guard = threading.Lock()
        self._repository.recover_interrupted_scans()

    def enqueue(self, job: Job, driver: ScannerDriver, request: ScanRequest) -> bool:
        """Schedule a queued job once, even if its idempotent request is retried."""
        with self._scheduled_guard:
            if job.identifier in self._scheduled:
                return False
            self._scheduled.add(job.identifier)
        thread = threading.Thread(target=self._run, args=(job.identifier, driver, request), daemon=True,
                                  name=f"devicebridge-scan-{job.identifier[:8]}")
        thread.start()
        return True

    def cancel(self, job_id: str) -> Job:
        job = self._required_scan(job_id)
        if job.state == JobState.QUEUED:
            cancelled = self._repository.cancel_queued(job_id, "Trabajo pendiente cancelado.")
            if cancelled:
                return cancelled
            job = self._required_scan(job_id)
        if job.state == JobState.PROCESSING:
            return self._repository.update(job_id, JobState.CANCEL_REQUESTED, error_code="CANCEL_REQUESTED",
                                           error_message="Cancelación solicitada; el controlador terminará la captura actual.")
        return job

    def _run(self, job_id: str, driver: ScannerDriver, request: ScanRequest) -> None:
        try:
            lock = self._device_lock(self._required_scan(job_id).device_id)
            with lock:
                job = self._required_scan(job_id)
                if job.state == JobState.CANCELLED:
                    return
                self._repository.update(job_id, JobState.PROCESSING)
                try:
                    result = driver.scan(request)
                    if self._required_scan(job_id).state == JobState.CANCEL_REQUESTED:
                        self._repository.update(job_id, JobState.CANCELLED, error_code="CANCELLED_BY_USER",
                                                error_message="Captura descartada por cancelación del usuario.")
                        return
                    path = self._file_store.write(job_id, result.filename_extension, result.content)
                    self._repository.update(job_id, JobState.COMPLETED, file_path=str(path), file_media_type=result.media_type)
                except UnsupportedScanOption as error:
                    self._fail_or_cancel(job_id, str(error), "Opción no compatible.")
                except ScannerDriverUnavailable as error:
                    self._fail_or_cancel(job_id, "SCANNER_DRIVER_UNAVAILABLE", f"No se pudo usar el escáner: {error}.")
                except (TwainScanError, WiaScanError) as error:
                    self._fail_or_cancel(job_id, "SCAN_FAILED", str(error))
                except Exception:
                    logger.exception("Error inesperado al procesar el escaneo %s.", job_id)
                    message = "Error interno de escaneo."
                    if self._debug_errors:
                        error = sys.exception()
                        message = f"{type(error).__name__}: {error}"
                    self._fail_or_cancel(job_id, "SCAN_FAILED", message)
        except KeyError:
            logger.debug("El trabajo de escaneo %s fue eliminado antes de ejecutarse.", job_id)
        finally:
            with self._scheduled_guard:
                self._scheduled.discard(job_id)

    def _device_lock(self, device_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(device_id, threading.Lock())

    def _required_scan(self, job_id: str) -> Job:
        job = self._repository.get(job_id)
        if not job or job.job_type != "scan":
            raise KeyError(job_id)
        return job

    def _fail_or_cancel(self, job_id: str, error_code: str, error_message: str) -> None:
        if self._required_scan(job_id).state == JobState.CANCEL_REQUESTED:
            self._repository.update(job_id, JobState.CANCELLED, error_code="CANCELLED_BY_USER",
                                    error_message="Captura cancelada por el usuario.")
            return
        self._repository.update(job_id, JobState.FAILED, error_code=error_code, error_message=error_message)
