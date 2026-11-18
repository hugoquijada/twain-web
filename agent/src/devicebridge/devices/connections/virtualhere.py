from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class VirtualHereState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    AVAILABLE = "AVAILABLE"
    CONNECTED_LOCAL = "CONNECTED_LOCAL"
    IN_USE_REMOTE = "IN_USE_REMOTE"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class VirtualHereDeviceStatus:
    address: str
    state: VirtualHereState
    detail: str

    def to_api(self) -> dict[str, str]:
        return {"address": self.address, "state": self.state, "detail": self.detail}


class VirtualHereError(RuntimeError):
    pass


class VirtualHereClient:
    """Narrow wrapper around the documented VirtualHere ``-t`` API.

    The command vocabulary is intentionally private and fixed. Callers provide
    only configured device addresses; no HTTP input ever becomes a shell command.
    """

    def __init__(self, executable_path: Path, timeout_seconds: int):
        self.executable_path = executable_path
        self.timeout_seconds = timeout_seconds

    def list_devices(self) -> str:
        return self._run("LIST")

    def get_device_status(self, address: str) -> VirtualHereDeviceStatus:
        response = self._run(f"DEVICE INFO,{address}")
        return _parse_status(address, response)

    def connect(self, address: str) -> VirtualHereDeviceStatus:
        response = self._run(f"USE,{address}")
        if not _is_ok(response):
            raise VirtualHereError(_safe_detail(response))
        return self.get_device_status(address)

    def disconnect(self, address: str) -> VirtualHereDeviceStatus:
        response = self._run(f"STOP USING,{address}")
        if not _is_ok(response):
            raise VirtualHereError(_safe_detail(response))
        return self.get_device_status(address)

    def _run(self, command: str) -> str:
        if not self.executable_path.is_file():
            raise VirtualHereError("El ejecutable de VirtualHere configurado no existe.")
        with tempfile.TemporaryDirectory(prefix="devicebridge-vh-") as directory:
            response_path = Path(directory) / "response.txt"
            arguments = [str(self.executable_path), "-t", command, f"-r={response_path}"]
            try:
                completed = subprocess.run(
                    arguments, check=False, shell=False, capture_output=True, text=True,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as error:
                raise VirtualHereError("VirtualHere no respondió dentro del tiempo configurado.") from error
            response = response_path.read_text(encoding="utf-8", errors="replace") if response_path.exists() else ""
            response = response.strip() or completed.stdout.strip() or completed.stderr.strip()
            if completed.returncode == 2:
                raise VirtualHereError(_safe_detail(response) or "VirtualHere rechazó la solicitud.")
            return response


class AgentConnectionRegistry:
    """Keeps ownership only for connections made during this process lifetime.

    A restart intentionally forgets ownership, preventing a later automatic
    disconnect of a device that a person reconnected manually.
    """

    def __init__(self):
        self._addresses: set[str] = set()

    def mark_connected(self, address: str) -> None:
        self._addresses.add(address)

    def owns(self, address: str) -> bool:
        return address in self._addresses

    def release(self, address: str) -> None:
        self._addresses.discard(address)


def _is_ok(response: str) -> bool:
    return response.strip().upper().startswith("OK")


def _parse_status(address: str, response: str) -> VirtualHereDeviceStatus:
    normalized = response.casefold()
    if "in use by another" in normalized or "in use remote" in normalized:
        state = VirtualHereState.IN_USE_REMOTE
    elif "in use by this client" in normalized or "connected locally" in normalized:
        state = VirtualHereState.CONNECTED_LOCAL
    elif "available" in normalized or "not in use" in normalized:
        state = VirtualHereState.AVAILABLE
    elif "not found" in normalized or "does not exist" in normalized:
        state = VirtualHereState.DISCONNECTED
    elif "error" in normalized or "failed" in normalized:
        state = VirtualHereState.ERROR
    else:
        state = VirtualHereState.UNKNOWN
    return VirtualHereDeviceStatus(address, state, _safe_detail(response))


def _safe_detail(value: str) -> str:
    return " ".join(value.split())[:500]
