from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ScannerCapabilities:
    sources: tuple[str, ...]
    color_modes: tuple[str, ...]
    resolutions: tuple[int, ...]
    formats: tuple[str, ...]
    duplex: bool
    max_pages: int | None

    def to_api(self) -> dict[str, object]:
        return {
            "sources": list(self.sources),
            "colorModes": list(self.color_modes),
            "resolutions": list(self.resolutions),
            "formats": list(self.formats),
            "duplex": self.duplex,
            "maxPages": self.max_pages,
        }


@dataclass(frozen=True)
class ScanRequest:
    source: str
    color_mode: str
    resolution: int
    output_format: str
    duplex: bool


@dataclass(frozen=True)
class ScanResult:
    content: bytes
    media_type: str
    filename_extension: str


class ScannerDriver(Protocol):
    identifier: str
    display_name: str

    def capabilities(self) -> ScannerCapabilities: ...

    def scan(self, request: ScanRequest) -> ScanResult: ...
