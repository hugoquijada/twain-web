import tempfile
import unittest
from pathlib import Path

from devicebridge.config import ConfigurationError, load_configuration


class ConfigurationTest(unittest.TestCase):
    def test_rejects_network_binding(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.yaml"
            path.write_text("""
agent:
  installation_id: test
  host: 0.0.0.0
  port: 8765
  data_directory: ./data
  temporary_directory: ./tmp
  retention_hours: 24
  allowed_origins: [https://sistema.example]
  api_token_environment: DEVICEBRIDGE_API_TOKEN
""", encoding="utf-8")

            with self.assertRaises(ConfigurationError):
                load_configuration(path)
