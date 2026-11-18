from __future__ import annotations

from .base import ScanRequest, ScanResult, ScannerCapabilities


class UnavailableScannerDriver:
    """Visible placeholder until the WIA/TWAIN driver is implemented and tested."""

    def __init__(self, identifier: str, display_name: str, technology: str):
        self.identifier = identifier
        self.display_name = display_name
        self.technology = technology

    def capabilities(self) -> ScannerCapabilities:
        return ScannerCapabilities((), (), (), (), False, None)

    def scan(self, request: ScanRequest) -> ScanResult:
        raise ScannerDriverUnavailable(self.technology)


class ScannerDriverUnavailable(RuntimeError):
    pass
