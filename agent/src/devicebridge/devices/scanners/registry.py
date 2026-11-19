from __future__ import annotations

import threading

from devicebridge.config import ScannerConfiguration
from devicebridge.storage.scanner_profiles import ScannerProfileRepository

from .simulated import SimulatedScannerDriver
from .twain import TwainScannerDriver
from .unavailable import UnavailableScannerDriver
from .wia import WiaScannerDriver


class ScannerRegistry:
    def __init__(self, repository: ScannerProfileRepository):
        self._repository = repository
        self._lock = threading.Lock()
        self._profiles: dict[str, ScannerConfiguration] = {}
        self._drivers = {}
        self.refresh()

    def refresh(self) -> None:
        profiles = {profile.identifier: profile for profile in self._repository.list()}
        with self._lock:
            self._drivers = {
                identifier: self._drivers[identifier]
                if self._profiles.get(identifier) == profile and identifier in self._drivers
                else _make_driver(profile)
                for identifier, profile in profiles.items()
            }
            self._profiles = profiles

    def snapshot(self):
        self.refresh()
        with self._lock:
            return dict(self._profiles), dict(self._drivers)


def _make_driver(scanner: ScannerConfiguration):
    if scanner.driver == "simulated":
        return SimulatedScannerDriver(scanner.identifier, scanner.display_name)
    if scanner.driver == "wia":
        return WiaScannerDriver(scanner.identifier, scanner.display_name, scanner.windows_device, scanner.default_source)
    if scanner.driver == "twain":
        return TwainScannerDriver(scanner.identifier, scanner.display_name, scanner.windows_device, scanner.default_source)
    return UnavailableScannerDriver(scanner.identifier, scanner.display_name, scanner.driver)
