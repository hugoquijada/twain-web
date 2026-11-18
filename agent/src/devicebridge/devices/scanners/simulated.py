from __future__ import annotations

import base64

from .base import ScanRequest, ScanResult, ScannerCapabilities


class SimulatedScannerDriver:
    """Deterministic adapter used only for development and automated tests."""

    _ONE_PIXEL_PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9J4hYAAAAASUVORK5CYII="
    )

    def __init__(self, identifier: str, display_name: str):
        self.identifier = identifier
        self.display_name = display_name

    def capabilities(self) -> ScannerCapabilities:
        return ScannerCapabilities(
            sources=("flatbed", "adf"), color_modes=("color", "grayscale", "black_and_white"),
            resolutions=(150, 300), formats=("png",), duplex=True, max_pages=50,
        )

    def scan(self, request: ScanRequest) -> ScanResult:
        capabilities = self.capabilities()
        if request.source not in capabilities.sources or request.color_mode not in capabilities.color_modes:
            raise UnsupportedScanOption("SOURCE_OR_COLOR_MODE_UNSUPPORTED")
        if request.resolution not in capabilities.resolutions or request.output_format not in capabilities.formats:
            raise UnsupportedScanOption("RESOLUTION_OR_FORMAT_UNSUPPORTED")
        if request.duplex and not capabilities.duplex:
            raise UnsupportedScanOption("DUPLEX_UNSUPPORTED")
        return ScanResult(self._ONE_PIXEL_PNG, "image/png", "png")


class UnsupportedScanOption(ValueError):
    pass
