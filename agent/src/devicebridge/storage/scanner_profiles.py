from __future__ import annotations

import secrets
import sqlite3
import threading
from pathlib import Path

from devicebridge.config import ScannerConfiguration


class ScannerProfileRepository:
    """Persistent local scanner profiles, independent from config.yaml."""

    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS scanner_profiles (
              id TEXT PRIMARY KEY, display_name TEXT NOT NULL, driver TEXT NOT NULL,
              windows_device TEXT NOT NULL, default_source TEXT NOT NULL,
              default_color_mode TEXT NOT NULL, default_resolution INTEGER NOT NULL,
              default_output_format TEXT NOT NULL, default_duplex INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS local_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self._connection.commit()

    def seed_if_empty(self, profiles: tuple[ScannerConfiguration, ...]) -> None:
        with self._lock:
            migrated = self._connection.execute(
                "SELECT 1 FROM local_settings WHERE key='scanner_profiles_seeded'"
            ).fetchone()
            if migrated:
                return
            count = self._connection.execute("SELECT COUNT(*) FROM scanner_profiles").fetchone()[0]
            if count == 0:
                for profile in profiles:
                    self._upsert(profile)
            self._connection.execute("INSERT INTO local_settings VALUES ('scanner_profiles_seeded', '1')")
            self._connection.commit()

    def list(self) -> tuple[ScannerConfiguration, ...]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM scanner_profiles ORDER BY display_name").fetchall()
        return tuple(_from_row(row) for row in rows)

    def upsert(self, profile: ScannerConfiguration) -> None:
        with self._lock:
            self._upsert(profile)
            self._connection.commit()

    def delete(self, identifier: str) -> bool:
        with self._lock:
            cursor = self._connection.execute("DELETE FROM scanner_profiles WHERE id=?", (identifier,))
            self._connection.commit()
        return cursor.rowcount == 1

    def admin_token(self) -> str:
        with self._lock:
            row = self._connection.execute("SELECT value FROM local_settings WHERE key='admin_token'").fetchone()
            if row:
                return row["value"]
            token = secrets.token_urlsafe(32)
            self._connection.execute("INSERT INTO local_settings VALUES ('admin_token', ?)", (token,))
            self._connection.commit()
            return token

    def _upsert(self, profile: ScannerConfiguration) -> None:
        self._connection.execute("""
            INSERT INTO scanner_profiles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, driver=excluded.driver,
              windows_device=excluded.windows_device, default_source=excluded.default_source,
              default_color_mode=excluded.default_color_mode, default_resolution=excluded.default_resolution,
              default_output_format=excluded.default_output_format, default_duplex=excluded.default_duplex
        """, (profile.identifier, profile.display_name, profile.driver, profile.windows_device,
              profile.default_source, profile.default_color_mode, profile.default_resolution,
              profile.default_output_format, int(profile.default_duplex)))


def _from_row(row: sqlite3.Row) -> ScannerConfiguration:
    return ScannerConfiguration(row["id"], row["display_name"], row["driver"], row["windows_device"],
                                row["default_source"], row["default_color_mode"], row["default_resolution"],
                                row["default_output_format"], bool(row["default_duplex"]))
