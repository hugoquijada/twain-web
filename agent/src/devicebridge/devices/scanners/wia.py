from __future__ import annotations

from .base import ScanRequest, ScanResult, ScannerCapabilities
from .simulated import UnsupportedScanOption
from .unavailable import ScannerDriverUnavailable


# WIA property IDs from the Windows Image Acquisition automation API.
_WIA_DEVICE_TYPE_SCANNER = 1
_WIA_IPS_XRES = 6147
_WIA_IPS_YRES = 6148
_WIA_IPS_DOCUMENT_HANDLING_SELECT = 3088
_WIA_DPS_DOCUMENT_HANDLING_SELECT = 3088
_WIA_DPS_DOCUMENT_HANDLING_STATUS = 3087
_WIA_FEEDER = 1
_WIA_DUPLEX = 4

_FORMATS = {
    "png": ("{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}", "image/png", "png"),
    "jpeg": ("{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}", "image/jpeg", "jpg"),
}


class WiaScannerDriver:
    """Windows Image Acquisition adapter for locally installed scanner drivers."""

    def __init__(self, identifier: str, display_name: str, windows_device: str, default_source: str) -> None:
        self.identifier = identifier
        self.display_name = display_name
        self.windows_device = windows_device
        self.default_source = default_source

    def capabilities(self) -> ScannerCapabilities:
        # WIA does not expose all capabilities until the device is connected. These are
        # the options supported by this first adapter; unsupported driver options fail
        # explicitly when WIA performs the transfer.
        return ScannerCapabilities(
            sources=("adf", "flatbed"),
            color_modes=("color", "grayscale", "black_and_white"),
            resolutions=(150, 200, 300, 600),
            formats=("png", "jpeg"),
            duplex=True,
            max_pages=1,
        )

    def scan(self, request: ScanRequest) -> ScanResult:
        if request.output_format not in _FORMATS:
            raise UnsupportedScanOption("OUTPUT_FORMAT_UNSUPPORTED_BY_WIA")
        if request.resolution not in self.capabilities().resolutions:
            raise UnsupportedScanOption("RESOLUTION_UNSUPPORTED")

        try:
            import pythoncom
            import win32com.client
        except ImportError as error:
            raise ScannerDriverUnavailable("wia (falta pywin32)") from error

        pythoncom.CoInitialize()
        try:
            device = self._connect(win32com.client.Dispatch("WIA.DeviceManager"))
            self._configure(device, request)
            item = device.Items[1]
            format_guid, media_type, extension = _FORMATS[request.output_format]
            image = item.Transfer(format_guid)
            return ScanResult(bytes(image.FileData.BinaryData), media_type, extension)
        except ScannerDriverUnavailable:
            raise
        except Exception as error:
            raise WiaScanError(_describe_com_error(error)) from error
        finally:
            pythoncom.CoUninitialize()

    def _connect(self, manager):
        discovered: list[str] = []
        for info in manager.DeviceInfos:
            if info.Type != _WIA_DEVICE_TYPE_SCANNER:
                continue
            name = _property_value(info.Properties, "Name")
            discovered.append(str(name))
            if self.windows_device.casefold() in str(name).casefold():
                return info.Connect()
        available = ", ".join(discovered) if discovered else "ninguno"
        raise ScannerDriverUnavailable(
            f"wia (no se encontró '{self.windows_device}'; dispositivos WIA detectados: {available})"
        )

    def _configure(self, device, request: ScanRequest) -> None:
        source = _WIA_FEEDER if request.source == "adf" else 0
        if request.duplex:
            source |= _WIA_DUPLEX
        _set_property_if_available(device.Properties, _WIA_DPS_DOCUMENT_HANDLING_SELECT, source)
        item = device.Items[1]
        _set_property_if_available(item.Properties, _WIA_IPS_XRES, request.resolution)
        _set_property_if_available(item.Properties, _WIA_IPS_YRES, request.resolution)


class WiaScanError(RuntimeError):
    pass


def _property_value(properties, name: str):
    try:
        return properties.Item(name).Value
    except Exception:
        return ""


def _set_property_if_available(properties, property_id: int, value: int) -> None:
    try:
        properties.Item(property_id).Value = value
    except Exception:
        # Drivers do not all expose the same WIA property set. Transfer will return
        # the driver's own error if the requested operation cannot be performed.
        pass


def _describe_com_error(error: Exception) -> str:
    message = str(error).strip()
    return message or "WIA no pudo completar el escaneo."
