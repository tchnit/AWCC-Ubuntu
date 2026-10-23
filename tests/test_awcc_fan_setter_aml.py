import importlib.util
from pathlib import Path
import sys
import unittest

RESEARCH = Path(__file__).resolve().parents[1] / "research"
sys.path.insert(0, str(RESEARCH))
spec = importlib.util.spec_from_file_location("awcc_fan_setter_aml", RESEARCH / "analyze_awcc_fan_setter.py")
decoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decoder)


def package(opcode, body):
    length = len(body) + 1
    if length < 64:
        return bytes((opcode, length)) + body
    length = len(body) + 2
    return bytes((opcode, 0x40 | (length & 15), length >> 4)) + body


def tree(channels):
    result = decoder.FAIL[:-1]
    for fan_id, field in reversed(channels):
        body = b"\x93DM21\x0a" + bytes((fan_id,))
        body += b"\x70DM22\x5e\x5e\x2f\x04PC00LPCBEC0_" + field + decoder.SUCCESS
        result = package(0xa0, body) + package(0xa1, result)
    return result + b"\xa5"


class FanSetterAmlTests(unittest.TestCase):
    def test_channel_tree_decodes_each_explicit_target(self):
        result = decoder.decode_channel_tree(tree(((0x32,b"C1FW"),(0x33,b"G1FW"),(0x3b,b"C2FW"),(0x3c,b"G2FW"))))
        self.assertEqual([x["fan_id"] for x in result], ["0x32","0x33","0x3b","0x3c"])
        self.assertTrue(result[2]["target_relative_to_AMW1"].endswith("C2FW"))

    def test_unknown_selector_assignment_or_reply_is_rejected(self):
        raw = tree(((0x32,b"C1FW"),))
        for changed in (raw.replace(b"DM21",b"DM20"), raw.replace(b"DM22",b"DM23"), raw.replace(b"PC00",b"PCI0"), raw.replace(decoder.SUCCESS,b"\x70\x01\x60\xa5"), raw + b"\x00", raw[:-1]):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                decoder.decode_channel_tree(changed)

    def test_duplicate_fan_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            decoder.decode_channel_tree(tree(((0x32,b"C1FW"),(0x32,b"C2FW"))))

    def test_saved_x17_table_maps_four_channels_without_execution(self):
        table = RESEARCH / "results/acpi-2026-10-09/DSDT"
        if not table.exists():
            self.skipTest("Saved firmware evidence unavailable")
        result = decoder.analyze(table.read_bytes())
        self.assertEqual(result["table_sha256"], "4a7c8c5a8adddca255bc414d0f92afe5db0d5f1b133644d710dfb2600900c9f4")
        self.assertEqual([x["target_relative_to_AMW1"].rsplit(".",1)[-1] for x in result["channels"]], ["C1FW","G1FW","C2FW","G2FW"])
        self.assertIn("RPM effects", result["limits"])
