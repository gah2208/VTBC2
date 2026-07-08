__version__ = "1.0.5"
# Copyright 2026 Gregory Howard  all rights reserved.

import hashlib
import os
from build_manifest import FILES


# ============================================================
# NEW IMPLEMENTATION (ACTIVE CODE)
# ============================================================

# NEW: use actual file paths from build_manifest
FILES_TO_CHECK = [data["path"] for data in FILES.values()]

CHECKSUM = "1e0ed3c34a1ddf37056edd3bfecbf189cdd1f73e1878a6231d405963b5cc427e"


def compute_checksum():
    sha = hashlib.sha256()

    for fname in sorted(FILES_TO_CHECK):
        if not os.path.exists(fname):
            raise Exception(f"Missing file: {fname}")
        with open(fname, "rb") as f:
            sha.update(f.read())

    return sha.hexdigest()


def verify_checksum():
    print("\n=== VTBC CHECKSUM VALIDATION START ===")

    current = compute_checksum()

    print(f"Expected: {CHECKSUM}")
    print(f"Actual  : {current}")

    if current != CHECKSUM:
        print("\n❌ CHECKSUM FAILED — FILES MODIFIED OR CORRUPTED\n")
        raise Exception("CHECKSUM MISMATCH")

    print("\n✅ CHECKSUM VERIFIED\n")
    print("======================================\n")
