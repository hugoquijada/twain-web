from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import Job, JobState


class JobInProgressError(Exception):
    def __init__(self, job: Job):
        self.job = job
        super().__init__(f"Ya existe un trabajo activo para {job.device_id}.")


class SQLiteJobRepository:
    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path, check_same_thread=False)
        self._lock = threading.RLock()
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              job_type TEXT NOT NULL,
              device_id TEXT NOT NULL,
              state TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              idempotency_key TEXT NOT NULL UNIQUE,
              error_code TEXT,
              error_message TEXT,
              file_path TEXT,
              file_media_type TEXT
            )
        """)
        self.connection.commit()

    def create_or_get(self, job_type: str, device_id: str, idempotency_key: str) -> Job:
        with self._lock:
            existing = self.get_by_idempotency_key(idempotency_key)
            if existing:
                if existing.job_type != job_type or existing.device_id != device_id:
                    raise ValueError("La clave de idempotencia ya pertenece a otra solicitud.")
                return existing
            now = _now()
            job = Job(str(uuid.uuid4()), job_type, device_id, JobState.QUEUED, now, now, idempotency_key)
            self.connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)",
                (job.identifier, job.job_type, job.device_id, job.state, now.isoformat(), now.isoformat(), job.idempotency_key),
            )
            self.connection.commit()
            return job

    def create_or_get_exclusive(self, job_type: str, device_id: str, idempotency_key: str) -> Job:
        """Creates at most one queued or active job per device."""
        with self._lock:
            existing = self.get_by_idempotency_key(idempotency_key)
            if existing:
                if existing.job_type != job_type or existing.device_id != device_id:
                    raise ValueError("La clave de idempotencia ya pertenece a otra solicitud.")
                return existing
            row = self.connection.execute(
                """SELECT * FROM jobs WHERE job_type=? AND device_id=? AND state IN (?, ?, ?)
                   ORDER BY created_at DESC LIMIT 1""",
                (job_type, device_id, JobState.QUEUED, JobState.PROCESSING, JobState.CANCEL_REQUESTED),
            ).fetchone()
            if row:
                raise JobInProgressError(_job_from_row(row))
            now = _now()
            job = Job(str(uuid.uuid4()), job_type, device_id, JobState.QUEUED, now, now, idempotency_key)
            self.connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)",
                (job.identifier, job.job_type, job.device_id, job.state, now.isoformat(), now.isoformat(), job.idempotency_key),
            )
            self.connection.commit()
            return job

    def get(self, identifier: str) -> Job | None:
        with self._lock:
            row = self.connection.execute("SELECT * FROM jobs WHERE id = ?", (identifier,)).fetchone()
        return _job_from_row(row) if row else None

    def get_by_idempotency_key(self, key: str) -> Job | None:
        with self._lock:
            row = self.connection.execute("SELECT * FROM jobs WHERE idempotency_key = ?", (key,)).fetchone()
        return _job_from_row(row) if row else None

    def update(self, identifier: str, state: JobState, *, error_code: str | None = None,
               error_message: str | None = None, file_path: str | None = None,
               file_media_type: str | None = None) -> Job:
        now = _now().isoformat()
        with self._lock:
            self.connection.execute(
                """UPDATE jobs SET state=?, updated_at=?, error_code=?, error_message=?,
                   file_path=COALESCE(?, file_path), file_media_type=COALESCE(?, file_media_type) WHERE id=?""",
                (state, now, error_code, error_message, file_path, file_media_type, identifier),
            )
            self.connection.commit()
        job = self.get(identifier)
        if not job:
            raise KeyError(identifier)
        return job

    def list(self, *, job_type: str | None = None) -> list[Job]:
        query = "SELECT * FROM jobs" + (" WHERE job_type = ?" if job_type else "") + " ORDER BY created_at DESC"
        with self._lock:
            rows = self.connection.execute(query, (job_type,) if job_type else ()).fetchall()
        return [_job_from_row(row) for row in rows]

    def delete(self, identifier: str) -> bool:
        with self._lock:
            result = self.connection.execute("DELETE FROM jobs WHERE id = ?", (identifier,))
            self.connection.commit()
        return result.rowcount == 1

    def cancel_queued(self, identifier: str, message: str) -> Job | None:
        now = _now().isoformat()
        with self._lock:
            result = self.connection.execute(
                """UPDATE jobs SET state=?, updated_at=?, error_code=?, error_message=?
                   WHERE id=? AND state=?""",
                (JobState.CANCELLED, now, "CANCELLED_BY_USER", message, identifier, JobState.QUEUED),
            )
            self.connection.commit()
        return self.get(identifier) if result.rowcount else None

    def recover_interrupted_scans(self) -> None:
        with self._lock:
            self.connection.execute(
                "UPDATE jobs SET state=?, error_code=?, error_message=?, updated_at=? WHERE job_type='scan' AND state IN (?, ?)",
                (JobState.UNCERTAIN, "AGENT_RESTARTED", "El agente se reinició durante la captura.", _now().isoformat(),
                 JobState.PROCESSING, JobState.CANCEL_REQUESTED),
            )
            self.connection.execute(
                "UPDATE jobs SET state=?, error_code=?, error_message=?, updated_at=? WHERE job_type='scan' AND state=?",
                (JobState.CANCELLED, "AGENT_RESTARTED", "El trabajo pendiente se canceló al reiniciar el agente.", _now().isoformat(), JobState.QUEUED),
            )
            self.connection.commit()


def _now() -> datetime:
    return datetime.now(UTC)


def _job_from_row(row: sqlite3.Row) -> Job:
    return Job(
        identifier=row["id"], job_type=row["job_type"], device_id=row["device_id"], state=JobState(row["state"]),
        created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
        idempotency_key=row["idempotency_key"], error_code=row["error_code"], error_message=row["error_message"],
        file_path=row["file_path"], file_media_type=row["file_media_type"],
    )
