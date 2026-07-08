__version__ = "1.1.1"
# Copyright 2026 Gregory Howard. All rights reserved.

import json
import os
import re
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(ROOT_DIR, "manifest.json")
CHECK_EXTENSIONS = {".py", ".json", ".bat", ".ps1"}

# NEW: build-time manifest checks are disabled by default at runtime.
# Set VTBC_ENABLE_MANIFEST_CHECK=1 to force-enable.
ENABLE_MANIFEST_CHECK = os.getenv("VTBC_ENABLE_MANIFEST_CHECK", "0").strip() == "1"


def get_root_files():
    files = []

    for name in sorted(os.listdir(ROOT_DIR)):
        path = os.path.join(ROOT_DIR, name)

        if not os.path.isfile(path):
            continue

        _, ext = os.path.splitext(name.lower())
        if ext in CHECK_EXTENSIONS:
            files.append(name)

    return files


def load_manifest():
    if not os.path.exists(MANIFEST_PATH):
        raise FileNotFoundError(f"manifest.json not found: {MANIFEST_PATH}")

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    manifest_files = {}
    for entry in data.get("files", []):
        manifest_files[entry.get("file")] = entry.get("version")

    return manifest_files


def extract_version(file_path):
    _, ext = os.path.splitext(file_path.lower())

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return None, f"READ ERROR: {e}"

    if ext == ".py":
        match = re.search(r'__version__\s*=\s*"([^"]+)"', content)
        if match:
            return match.group(1), None
        return None, "VERSION NOT FOUND"

    if ext == ".json":
        try:
            data = json.loads(content)
            version = data.get("__version__") or data.get("version")
            if version is not None:
                return str(version), None
            return None, "VERSION NOT FOUND"
        except Exception as e:
            return None, f"INVALID JSON: {e}"

    if ext in {".bat", ".ps1"}:
        match = re.search(r'__version__\s*=\s*"([^"]+)"', content, re.IGNORECASE)
        if match:
            return match.group(1), None
        match = re.search(r'\bversion\b\s*[:=]\s*"([^"]+)"', content, re.IGNORECASE)
        if match:
            return match.group(1), None
        return None, "VERSION NOT FOUND"

    return None, "UNSUPPORTED FILE TYPE"


def run_build_check():
    # DISABLED BY DEFAULT: manifest is a development/build artifact, not runtime requirement.
    if not ENABLE_MANIFEST_CHECK:
        print("=== MANIFEST CHECK ===")
        print("SKIPPED (runtime mode): set VTBC_ENABLE_MANIFEST_CHECK=1 to enable.")
        return True

    manifest_versions = load_manifest()
    root_files = get_root_files()

    print("=== MANIFEST CHECK ===")
    print()

    failures = []

    for name in root_files:
        path = os.path.join(ROOT_DIR, name)
        actual_version, actual_error = extract_version(path)

        if name not in manifest_versions:
            print(f"FAIL | {name} | manifest=MISSING | actual={actual_version or actual_error}")
            failures.append(name)
            continue

        expected_version = manifest_versions[name]

        if actual_error:
            print(f"FAIL | {name} | manifest={expected_version} | actual={actual_error}")
            failures.append(name)
            continue

        if expected_version != actual_version:
            print(f"FAIL | {name} | manifest={expected_version} | actual={actual_version}")
            failures.append(name)
        else:
            print(f"PASS | {name} | manifest={expected_version} | actual={actual_version}")

    manifest_only = sorted(set(manifest_versions.keys()) - set(root_files))
    for name in manifest_only:
        print(f"FAIL | {name} | manifest={manifest_versions[name]} | actual=FILE MISSING FROM ROOT")
        failures.append(name)

    print()
    print(f"Checked files: {len(root_files)}")
    print(f"Failures: {len(failures)}")

    if failures:
        print("BUILD CHECK FAILED")
        sys.exit(1)

    print("BUILD CHECK PASSED")
    return True


if __name__ == "__main__":
    run_build_check()