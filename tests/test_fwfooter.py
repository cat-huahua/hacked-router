"""Synthetic footer fixtures: no firmware, device data, or keys in the repo."""

import importlib.util
from pathlib import Path
import struct
import unittest
import zlib

_spec = importlib.util.spec_from_file_location(
    "fwfooter", Path(__file__).resolve().parents[1] / "fwfooter.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
inspect_footer = _module.inspect_footer


class FooterTests(unittest.TestCase):
    def fixture(self):
        payload = b"synthetic firmware\x00\xff"
        trailer = struct.pack(
            "<5I", zlib.crc32(payload) ^ 0xFFFFFFFF, 0x11223344,
            0x63138, 0x55667788, 0x99AABBCC,
        )
        footer = bytearray(0x10000)
        struct.pack_into("<III", footer, 0, 0, len(payload + trailer), 2)
        footer[0x28C:0x290] = b"HDR0"
        return bytearray(payload + trailer + footer)

    def test_offsets_endianness_and_crc(self):
        data = self.fixture()
        result = inspect_footer(data)
        self.assertEqual(result["footer_offset"], len(data) - 0x10000)
        trailer = result["legacy_trailer"]
        self.assertEqual(trailer["offset"], result["footer_offset"] - 20)
        self.assertEqual(trailer["chip_id"], "00063138")
        self.assertEqual(trailer["uninterpreted_words"],
                         [0x11223344, 0x55667788, 0x99AABBCC])
        self.assertTrue(trailer["crc_matches"])
        self.assertTrue(result["hdr0_magic_matches"])
        self.assertTrue(result["covered_length_equals_footer_offset"])
        self.assertIsNone(result["signature_verified"])

    def test_payload_corruption_is_not_validated(self):
        data = self.fixture()
        data[0] ^= 1
        result = inspect_footer(data)
        self.assertFalse(result["legacy_trailer"]["crc_matches"])
        self.assertIsNone(result["signature_verified"])

    def test_out_of_bounds_length_and_key_zero(self):
        data = self.fixture()
        struct.pack_into("<II", data, len(data) - 0x10000 + 4,
                         len(data) + 1, 0)
        result = inspect_footer(data)
        self.assertFalse(result["covered_length_within_payload"])
        self.assertFalse(result["key_index_in_intended_range"])
        self.assertIsNone(result["covered_sha256"])

    def test_bad_magic_remains_a_structural_report(self):
        data = self.fixture()
        data[-0x10000 + 0x28C] = 0
        self.assertFalse(inspect_footer(data)["hdr0_magic_matches"])

    def test_short_image_rejected(self):
        for length in (0, 0x28F, 0xFFFF, 0x10013):
            with self.subTest(length=length), self.assertRaises(ValueError):
                inspect_footer(bytes(length))
