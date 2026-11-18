import unittest

from devicebridge.devices.connections.virtualhere import (
    AgentConnectionRegistry,
    VirtualHereState,
    _parse_status,
)
from devicebridge.devices.scanners.twain import _is_initialization_error


class VirtualHereStateTest(unittest.TestCase):
    def test_recognizes_remote_usage(self):
        status = _parse_status("hub.114", "Device is in use by another client")
        self.assertEqual(VirtualHereState.IN_USE_REMOTE, status.state)

    def test_unknown_status_stays_unknown(self):
        status = _parse_status("hub.114", "VirtualHere response without documented state")
        self.assertEqual(VirtualHereState.UNKNOWN, status.state)

    def test_registry_forgets_a_released_address(self):
        registry = AgentConnectionRegistry()
        registry.mark_connected("hub.114")
        self.assertTrue(registry.owns("hub.114"))
        registry.release("hub.114")
        self.assertFalse(registry.owns("hub.114"))

    def test_recognizes_a_twain_initialization_failure(self):
        self.assertTrue(_is_initialization_error(RuntimeError("No se pudo inicializar el origen TWAIN")))
        self.assertFalse(_is_initialization_error(RuntimeError("El alimentador no tiene papel")))
