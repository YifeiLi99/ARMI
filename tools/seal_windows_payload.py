"""Seal a standalone wheel installation without build-machine path dependencies."""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import shutil
import struct
from pathlib import Path

from armi_admin.application.package_identity import admin_package_set_digest
from armi_postgresql_contract import (
    BASELINE_IDENTITY,
    role_policy_digest,
    schema_resource_digest,
)


def normalize_stripped_certificates(root: Path) -> None:
    """Fix stale certificate pointers in the locked standalone Python build.

    These five already-unsigned DLLs were truncated exactly at the old signature
    start upstream. Never remove an existing certificate or change image code.
    """
    for relative in (
        "DLLs/tcl86t.dll",
        "DLLs/tk86t.dll",
        "DLLs/zlib1.dll",
        "tcl/dde1.4/tcldde14.dll",
        "tcl/reg1.3/tclreg13.dll",
    ):
        path = root / "runtime/python" / relative
        raw = bytearray(path.read_bytes())
        pe = struct.unpack_from("<I", raw, 60)[0]
        if (
            raw[:2] != b"MZ"
            or raw[pe : pe + 4] != b"PE\0\0"
            or struct.unpack_from("<H", raw, pe + 24)[0] != 0x20B
        ):
            raise ValueError("INSTALLER-PYTHON-PE-FORMAT")
        entry = pe + 24 + 112 + 4 * 8
        offset, size = struct.unpack_from("<II", raw, entry)
        if (offset, size) == (0, 0):
            continue
        if offset != len(raw) or size == 0:
            raise ValueError("INSTALLER-PYTHON-CERTIFICATE-UNEXPECTED")
        struct.pack_into("<II", raw, entry, 0, 0)
        path.write_bytes(raw)
        imagehlp = ctypes.WinDLL("imagehlp")
        checksum = imagehlp.MapFileAndCheckSumW
        checksum.argtypes = [
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        checksum.restype = ctypes.c_uint32
        original, calculated = ctypes.c_uint32(), ctypes.c_uint32()
        if checksum(str(path), ctypes.byref(original), ctypes.byref(calculated)):
            raise ValueError("INSTALLER-PYTHON-PE-CHECKSUM")
        struct.pack_into("<I", raw, pe + 24 + 64, calculated.value)
        path.write_bytes(raw)


def seal(root: Path) -> None:
    root = root.resolve(strict=True)
    site = root / "runtime/python/Lib/site-packages"
    if not (site / "armi_admin").is_dir():
        raise ValueError("INSTALLER-NOT-A-PAYLOAD")
    if {path.name for path in root.glob("*.exe")} != {"ARMI.exe"}:
        raise ValueError("INSTALLER-ENTRYPOINT-INVENTORY")
    normalize_stripped_certificates(root)
    # Wheel console launchers contain absolute shebangs. Public native launchers
    # live at the program root; Runtime workers use the private sys.executable.
    scripts = (root / "runtime/python/Scripts").resolve()
    if not scripts.is_relative_to(root):
        raise ValueError("INSTALLER-SEAL-BOUNDARY")
    if scripts.exists():
        shutil.rmtree(scripts)
    # python-docx ships its editable template sources as well as default.docx.
    # Document() reads the latter; the unused source tree contains the OPC
    # reserved [Content_Types].xml name that cannot be a nested MSIX payload part.
    template_sources = (site / "docx/templates/default-docx-template").resolve()
    if not template_sources.is_relative_to(root):
        raise ValueError("INSTALLER-SEAL-BOUNDARY")
    if template_sources.exists():
        if not (template_sources.parent / "default.docx").is_file():
            raise ValueError("INSTALLER-DOCX-TEMPLATE-MISSING")
        shutil.rmtree(template_sources)
    for metadata in site.glob("*.dist-info"):
        removed = {"direct_url.json", "uv_cache.json"}
        for name in removed:
            (metadata / name).unlink(missing_ok=True)
        record = metadata / "RECORD"
        if not record.exists():
            continue
        with record.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
        kept = [row for row in rows if (site / row[0]).is_file()]
        with record.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream, lineterminator="\n").writerows(kept)
    for cache in sorted(
        root.rglob("__pycache__"), key=lambda path: len(path.parts), reverse=True
    ):
        if not cache.resolve().is_relative_to(root):
            raise ValueError("INSTALLER-SEAL-BOUNDARY")
        shutil.rmtree(cache)
    inventory: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "bundle.json":
            with path.open("rb") as stream:
                inventory[path.relative_to(root).as_posix()] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    manifest: dict[str, object] = {
        "schema_version": "armi.windows-bundle.v2",
        "target": "windows-11-x64",
        "database": {
            "postgresql": "18.4",
            "vector": "0.8.6",
            "pg_trgm": "1.6",
            "baseline": BASELINE_IDENTITY,
            "schema_digest": schema_resource_digest(),
            "role_policy_digest": role_policy_digest(),
        },
        "package_set_digest": admin_package_set_digest(),
        "files": inventory,
    }
    manifest["package_id"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    (root / "bundle.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    seal(parser.parse_args().root)
