# config_gen.py
__version__ = "1.0.1"
# Copyright 2026 Gregory Howard  all rights reserved.

# AUTO-GENERATED CONFIG GENERATOR
# Generates a compatibility config.py from admin_config_default.json + config.json
# Writes atomically to avoid partial imports.

from pathlib import Path
import json
from typing import Any, Dict

# Use the project's config_loader to produce the canonical merged config
from config_loader import load_merged_config

BASE_DIR = Path(__file__).parent
TARGET = BASE_DIR / "config.py"


def _json_to_python_literal(obj: Any) -> str:
    """
    Convert a JSON-compatible Python object to a valid Python literal string.
    Handles booleans, None, strings, numbers, lists, and dicts.
    """
    if obj is None:
        return "None"
    elif isinstance(obj, bool):
        # Must check bool before int, since bool is a subclass of int
        return "True" if obj else "False"
    elif isinstance(obj, str):
        return repr(obj)
    elif isinstance(obj, (int, float)):
        return repr(obj)
    elif isinstance(obj, list):
        items = [_json_to_python_literal(item) for item in obj]
        return "[" + ", ".join(items) + "]"
    elif isinstance(obj, dict):
        items = [f"{repr(k)}: {_json_to_python_literal(v)}" for k, v in obj.items()]
        return "{" + ", ".join(items) + "}"
    else:
        # Fallback for unknown types
        return repr(obj)


def _render_py(merged: Dict[str, Any]) -> str:
    lines = []
    lines.append("# AUTO-GENERATED — DO NOT EDIT")
    lines.append("from typing import Any, Dict")
    lines.append("")
    
    # Dump CONFIG as a Python dict literal (not JSON)
    config_str = "CONFIG: Dict[str, Any] = " + _json_to_python_literal(merged)
    lines.append(config_str)
    lines.append("")
    
    # Export flat names for legacy imports
    for k, v in merged.items():
        # Use our custom converter to ensure Python-valid literals
        lines.append(f"{k} = {_json_to_python_literal(v)}")
    
    lines.append("")
    lines.append("__all__ = ['CONFIG'] + " + repr(list(merged.keys())))
    return "\n".join(lines) + "\n"


def generate_config_py(target_path: Path | None = None) -> None:
    """
    Generate config.py atomically from the merged JSON config.
    """
    if target_path is None:
        target_path = TARGET

    merged = load_merged_config()

    content = _render_py(merged)

    tmp = target_path.with_suffix(".py.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target_path)