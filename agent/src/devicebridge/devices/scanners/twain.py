from __future__ import annotations

import logging
import threading
import time
from io import BytesIO

from .base import ScanRequest, ScanResult, ScannerCapabilities
from .simulated import UnsupportedScanOption
from .unavailable import ScannerDriverUnavailable


logger = logging.getLogger(__name__)
_INITIALIZATION_ATTEMPTS = 3


class TwainScannerDriver:
    """TWAIN adapter backed by NAPS2's Windows TWAIN bridge.

    The bridge loads the installed vendor TWAIN data source, which makes this
    suitable for HP devices whose ADF, duplex and image options are not fully
    exposed through WIA.
    """

    def __init__(self, identifier: str, display_name: str, windows_device: str, default_source: str) -> None:
        self.identifier = identifier
        self.display_name = display_name
        self.windows_device = windows_device
        self.default_source = default_source
        self._scan_lock = threading.Lock()

    def capabilities(self) -> ScannerCapabilities:
        # Real capability interrogation requires opening the physical TWAIN source.
        # These are the request options handled by the bridge; the driver will
        # explicitly report an error if a particular source does not support one.
        return ScannerCapabilities(
            sources=("flatbed", "adf"),
            color_modes=("color", "grayscale", "black_and_white"),
            resolutions=(150, 200, 300, 600),
            formats=("png", "jpeg", "pdf"),
            duplex=True,
            max_pages=1,
        )

    def scan(self, request: ScanRequest) -> ScanResult:
        if request.resolution not in self.capabilities().resolutions:
            raise UnsupportedScanOption("RESOLUTION_UNSUPPORTED")
        if request.output_format not in {"png", "jpeg", "pdf"}:
            raise UnsupportedScanOption("OUTPUT_FORMAT_UNSUPPORTED_BY_TWAIN")

        try:
            from naps2_scan import ColorMode, Driver, PaperSource, Scanner, list_devices
        except ImportError as error:
            raise ScannerDriverUnavailable("twain (falta naps2-scan)") from error

        try:
            with self._scan_lock:
                pages = self._capture_pages(Driver, Scanner, list_devices, ColorMode, PaperSource, request)
            if not pages:
                raise TwainScanError("El controlador TWAIN no devolvió ninguna página.")
            if len(pages) > 1:
                logger.warning("TWAIN devolvió %s páginas; el adaptador actual entregará solo la primera.", len(pages))
            return _encode(pages[0], request.output_format)
        except (ScannerDriverUnavailable, UnsupportedScanOption):
            raise
        except Exception as error:
            raise TwainScanError(str(error) or "TWAIN no pudo completar el escaneo.") from error

    def _capture_pages(self, Driver, Scanner, list_devices, ColorMode, PaperSource, request: ScanRequest):
        for attempt in range(1, _INITIALIZATION_ATTEMPTS + 1):
            try:
                devices = list_devices(driver=Driver.TWAIN)
                device = next((candidate for candidate in devices if _matches(candidate, self.windows_device)), None)
                if device is None:
                    raise ScannerDriverUnavailable(f"twain (no se encontró '{self.windows_device}')")
                color_mode = {
                    "color": ColorMode.COLOR,
                    "grayscale": ColorMode.GRAY,
                    "black_and_white": ColorMode.BW,
                }[request.color_mode]
                paper_source = PaperSource.DUPLEX if request.duplex else (
                    PaperSource.FEEDER if request.source == "adf" else PaperSource.FLATBED
                )
                with Scanner(device) as scanner:
                    return list(scanner.scan(
                        dpi=request.resolution, color_mode=color_mode, paper_source=paper_source, use_native_ui=False
                    ))
            except ScannerDriverUnavailable:
                raise
            except Exception as error:
                if attempt == _INITIALIZATION_ATTEMPTS or not _is_initialization_error(error):
                    raise
                logger.warning("TWAIN no se inicializó (intento %s/%s): %s", attempt, _INITIALIZATION_ATTEMPTS, error)
                _pause_before_retry(attempt)
        return []


class TwainScanError(RuntimeError):
    pass


def _is_initialization_error(error: Exception) -> bool:
    message = str(error).casefold()
    return any(term in message for term in ("initialize", "initialise", "inicializar", "initialization", "inicialización"))


def _pause_before_retry(attempt: int) -> None:
    time.sleep(0.5 * attempt)


def _matches(device, configured_name: str) -> bool:
    expected = configured_name.casefold()
    return expected in device.name.casefold() or expected == device.id.casefold()


def _encode(image, output_format: str) -> ScanResult:
    buffer = BytesIO()
    if output_format == "png":
        image.save(buffer, format="PNG")
        return ScanResult(buffer.getvalue(), "image/png", "png")
    if output_format == "jpeg":
        image.convert("RGB").save(buffer, format="JPEG", quality=90)
        return ScanResult(buffer.getvalue(), "image/jpeg", "jpg")
    image.convert("RGB").save(buffer, format="PDF")
    return ScanResult(buffer.getvalue(), "application/pdf", "pdf")
