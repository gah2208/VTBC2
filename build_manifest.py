__version__ = "1.3.2"
# Copyright 2026 Gregory Howard

import json
import os
import re
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(ROOT_DIR, "manifest.json")
TARGET_EXTENSIONS = {".py", ".ps1"}

EXCLUDED_FILES = {
    "build_check.py",
    "build_manifest.py",
    "qualification_test.py",
    "verify_imports.py",
    "vtbc_onboard.py",
}


def get_root_files():
    files = []

    for name in sorted(os.listdir(ROOT_DIR)):
        path = os.path.join(ROOT_DIR, name)

        if not os.path.isfile(path):
            continue

        lower_name = name.lower()
        _, ext = os.path.splitext(lower_name)

        if ext == ".json":
            continue

        if lower_name in EXCLUDED_FILES:
            continue

        if ext in TARGET_EXTENSIONS:
            files.append(name)

    return files


def extract_version(file_path):
    _, ext = os.path.splitext(file_path.lower())

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    if ext == ".py":
        match = re.search(r'__version__\s*=\s*"([^"]+)"', content)
        if match:
            return match.group(1)

    elif ext == ".ps1":
        match = re.search(r'__version__\s*=\s*"([^"]+)"', content, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'\bversion\b\s*[:=]\s*"([^"]+)"', content, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def build_manifest():
    manifest = {
        "generated_at": datetime.now().isoformat(),
        "files": []
    }

    root_files = get_root_files()

    for name in root_files:
        path = os.path.join(ROOT_DIR, name)
        version = extract_version(path)

        manifest["files"].append({
            "file": name,
            "version": version
        })

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Created manifest: {MANIFEST_PATH}")
    print()

    for entry in manifest["files"]:
        version_display = entry["version"] if entry["version"] is not None else "VERSION NOT FOUND"
        print(f"{entry['file']}: {version_display}")

    return manifest


if __name__ == "__main__":
    build_manifest()