#!/usr/bin/env python3
"""Inspect the Arcadyan 64 KiB footer layout without reading or exporting keys.

Layout recovered from WG9116AEAC23-ST libcms_util.so. This reports structural
observations, NOT successful signature verification or device compatibility.
See docs/singtel-firmware-footer.md for offsets and evidence.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

FOOTER_SIZE = 0x10000
HEADER_SIZE = 0x290
LEGACY_TRAILER_SIZE = 0x14


def inspect_footer(data: bytes) -> dict:
    """Return only metadata; never output opaque envelope or key bytes."""
    if len(data) < FOOTER_SIZE + LEGACY_TRAILER_SIZE:
        raise ValueError("image is too short for a footer and legacy trailer")
    tail_offset = len(data) - FOOTER_SIZE
    trailer_offset = tail_offset - LEGACY_TRAILER_SIZE
    footer = data[tail_offset:]
    reserved, covered_length, key_index = struct.unpack_from("<III", footer)
    magic = footer[0x28C:HEADER_SIZE]
    crc, unused_4, chip_id, unused_12, unused_16 = struct.unpack_from(
        "<5I", data, trailer_offset
    )
    computed_crc = zlib.crc32(data[:trailer_offset]) ^ 0xFFFFFFFF
    length_in_bounds = covered_length <= tail_offset
    return {
        "image_size": len(data),
        "image_sha256": hashlib.sha256(data).hexdigest(),
        "footer_offset": tail_offset,
        "footer_size": FOOTER_SIZE,
        "header_size": HEADER_SIZE,
        "hdr0_magic_matches": magic == b"HDR0",
        "reserved_word": reserved,
        "covered_length": covered_length,
        "covered_length_within_payload": length_in_bounds,
        "covered_length_equals_footer_offset": covered_length == tail_offset,
        "key_index": key_index,
        "key_index_in_intended_range": 1 <= key_index <= 6,
        "covered_sha256": (
            hashlib.sha256(data[:covered_length]).hexdigest()
            if length_in_bounds else None
        ),
        "envelopes": {
            "region": {"relative_offset": 0xC, "size": 0x140},
            "header": {"relative_offset": 0x14C, "size": 0x140},
        },
        "legacy_trailer": {
            "offset": trailer_offset,
            "stored_crc": f"{crc:08x}",
            "computed_crc": f"{computed_crc:08x}",
            "crc_matches": crc == computed_crc,
            "chip_id": f"{chip_id:08x}",
            "uninterpreted_words": [unused_4, unused_12, unused_16],
        },
        "signature_verified": None,
        "verification_note": (
            "Structural inspection only; no envelope decryption, signature "
            "verification, or device compatibility check was performed."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="local firmware image")
    args = parser.parse_args()
    try:
        report = inspect_footer(args.image.read_bytes())
    except (OSError, ValueError) as exc:
        print(f"fwfooter: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
