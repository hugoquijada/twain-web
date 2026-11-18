from __future__ import annotations

from pathlib import Path


class TemporaryFileStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(self, job_id: str, extension: str, content: bytes) -> Path:
        path = self.directory / f"{job_id}.{extension}"
        path.write_bytes(content)
        return path
