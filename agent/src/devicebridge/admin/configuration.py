from __future__ import annotations

import difflib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from devicebridge.config import ConfigurationError, load_configuration


@dataclass(frozen=True)
class ConfigurationPreview:
    source_path: Path
    candidate_path: Path
    diff: str


def prepare_scanner_update(config_path: Path, scanner_id: str, values: dict[str, Any]) -> ConfigurationPreview:
    original = config_path.read_text(encoding="utf-8")
    yaml = YAML()
    yaml.preserve_quotes = True
    document = yaml.load(original) or {}
    scanners = document.get("scanners")
    if not isinstance(scanners, list):
        raise ConfigurationError("No hay escáneres configurados.")
    scanner = next((item for item in scanners if isinstance(item, dict) and item.get("id") == scanner_id), None)
    if scanner is None:
        raise ConfigurationError("El escáner seleccionado ya no existe en la configuración.")
    scanner.update(values)
    output = StringIO()
    yaml.dump(document, output)
    candidate_text = output.getvalue()
    candidate_path = config_path.with_suffix(config_path.suffix + ".candidate")
    candidate_path.write_text(candidate_text, encoding="utf-8")
    load_configuration(candidate_path)
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True), candidate_text.splitlines(keepends=True),
        fromfile=str(config_path), tofile=str(candidate_path),
    ))
    return ConfigurationPreview(config_path, candidate_path, diff)


def apply_preview(preview: ConfigurationPreview) -> Path:
    if not preview.candidate_path.is_file():
        raise ConfigurationError("La vista previa ya no está disponible.")
    load_configuration(preview.candidate_path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = preview.source_path.with_suffix(preview.source_path.suffix + f".{timestamp}.bak")
    shutil.copy2(preview.source_path, backup_path)
    os.replace(preview.candidate_path, preview.source_path)
    return backup_path
