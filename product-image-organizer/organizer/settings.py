from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .core import Options, UserError


@dataclass
class Preferences:
    output_format: str = "original"
    width: int = 800
    height: int = 800
    quality: str = "balanced"
    remember: bool = True
    theme: str = "system"
    last_options: dict | None = None
    last_output_parent: str = ""


def load_preferences(path: Path) -> Preferences:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        prefs = Preferences(**{k: v for k, v in data.items() if k in Preferences.__dataclass_fields__})
        Options(width=prefs.width, height=prefs.height, resize=True, quality=prefs.quality,
                output_format=prefs.output_format).validate()
        if prefs.theme not in ("light", "dark", "system") or type(prefs.remember) is not bool:
            raise ValueError()
        if not isinstance(prefs.last_output_parent, str):
            prefs.last_output_parent = ""
        return prefs
    except (OSError, ValueError, TypeError, AttributeError, UserError):
        return Preferences()


def save_preferences(path: Path, prefs: Preferences):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(prefs)
    if not prefs.remember:
        data["last_options"] = None
        data["last_output_parent"] = ""
    fd, name = tempfile.mkstemp(prefix="preferences-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
