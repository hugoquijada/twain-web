from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class Job:
    identifier: str
    job_type: str
    device_id: str
    state: JobState
    created_at: datetime
    updated_at: datetime
    idempotency_key: str
    error_code: str | None = None
    error_message: str | None = None
    file_path: str | None = None
    file_media_type: str | None = None

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "type": self.job_type,
            "deviceId": self.device_id,
            "state": self.state,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "error": None if not self.error_code else {"code": self.error_code, "message": self.error_message},
            "fileAvailable": self.file_path is not None,
        }
