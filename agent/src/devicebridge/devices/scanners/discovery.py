from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectedScanner:
    technology: str
    name: str
    identifier: str


def discover_scanners() -> tuple[list[DetectedScanner], list[str]]:
    """Discover sources without failing the administrative interface.

    Each backend is independently optional. A missing driver is reported to the
    user instead of making a healthy agent appear unavailable.
    """
    devices: list[DetectedScanner] = []
    diagnostics: list[str] = []
    _discover_twain(devices, diagnostics)
    _discover_wia(devices, diagnostics)
    return devices, diagnostics


def _discover_twain(devices: list[DetectedScanner], diagnostics: list[str]) -> None:
    try:
        from naps2_scan import Driver, list_devices
        for device in list_devices(driver=Driver.TWAIN):
            devices.append(DetectedScanner("TWAIN", str(device.name), str(device.id)))
    except Exception as error:
        diagnostics.append(f"TWAIN: {str(error) or 'no disponible'}")


def _discover_wia(devices: list[DetectedScanner], diagnostics: list[str]) -> None:
    try:
        import pythoncom
        import win32com.client
    except Exception as error:
        diagnostics.append(f"WIA: {str(error) or 'pywin32 no disponible'}")
        return
    pythoncom.CoInitialize()
    try:
        manager = win32com.client.Dispatch("WIA.DeviceManager")
        for info in manager.DeviceInfos:
            if info.Type == 1:
                name = _wia_property(info.Properties, "Name")
                devices.append(DetectedScanner("WIA", str(name), str(info.DeviceID)))
    except Exception as error:
        diagnostics.append(f"WIA: {str(error) or 'no disponible'}")
    finally:
        pythoncom.CoUninitialize()


def _wia_property(properties, name: str) -> str:
    try:
        return str(properties.Item(name).Value)
    except Exception:
        return "Escáner WIA sin nombre"
