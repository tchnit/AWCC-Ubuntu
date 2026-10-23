#!/usr/bin/python3
"""Strict static decoder of the saved x17 WMAX 0x15/2 fan dispatch.

Not an AML interpreter. Never reads live EC, evaluates WMI, or writes hardware.
The external fields' physical effects are intentionally NOT inferred here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import analyze_awcc_aml as aml

FAIL = b"\x70\x0c\xff\xff\xff\xff\x60\xa5"
SUCCESS = b"\x70\x00\x60"


def checked_if(data: bytes, offset: int, selector: bytes):
    if data[offset:offset + 1] != b"\xa0":
        raise ValueError("Expected If")
    predicate, end = aml.pkg(data, offset + 1)
    if data[predicate:predicate + 5] != b"\x93" + selector:
        raise ValueError("Unknown predicate/selector")
    value, body = aml.integer(data, predicate + 5)
    if body > end:
        raise ValueError("Predicate outside If")
    return value, body, end


def checked_else(data: bytes, offset: int):
    if data[offset:offset + 1] != b"\xa1":
        raise ValueError("Missing Else")
    return aml.pkg(data, offset + 1)


def decode_channel_tree(data: bytes) -> list[dict]:
    """Recognize only Store(DM22, ^^PC00.LPCB.EC0_.<field>) cases."""
    if data[-1:] != b"\xa5":
        raise ValueError("Missing shared fan-operation Break")
    offset, expected_end = 0, len(data) - 1
    channels = []
    while True:
        fan_id, body, end = checked_if(data, offset, b"DM21")
        prefix = b"\x70DM22\x5e\x5e\x2f\x04PC00LPCBEC0_"
        if data[body:body + len(prefix)] != prefix:
            raise ValueError("Unknown fan field assignment/path")
        field_start = body + len(prefix)
        raw_field = data[field_start:field_start + 4]
        if len(raw_field) != 4 or not all(c == 95 or 48 <= c <= 57 or 65 <= c <= 90 for c in raw_field):
            raise ValueError("Invalid AML NameSeg")
        if data[field_start + 4:end] != SUCCESS:
            raise ValueError("Unknown success reply or trailing fan body")
        channels.append({"fan_id": f"0x{fan_id:02x}", "argument": "DM22 (third input byte)",
                         "target_relative_to_AMW1": "^^PC00.LPCB.EC0_." + raw_field.decode("ascii")})
        next_body, next_end = checked_else(data, end)
        if next_end != expected_end:
            raise ValueError("Unhandled trailing channel terms")
        if data[next_body:next_end] == FAIL[:-1]:
            break
        offset, expected_end = next_body, next_end
    ids = [item["fan_id"] for item in channels]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate fan ID")
    return channels


def analyze(data: bytes) -> dict:
    outer = aml.analyze(data)  # Validates table, WMAX arguments and dispatcher.
    branch = next(item for item in outer["branches"] if int(item["method_id"], 16) == 0x15)
    start, stop = int(branch["body_start"], 16), int(branch["body_end"], 16)
    body = data[start:stop]
    if body[:1] != b"\xa2":
        raise ValueError("Missing thermal-control While")
    cursor, loop_end = aml.pkg(body, 1)
    preamble = b"\x01\x70DM20_T_3"
    if body[cursor:cursor + len(preamble)] != preamble or body[loop_end:] != b"\xa5":
        raise ValueError("Unknown operation selector/loop tail")
    operation1, _, first_end = checked_if(body, cursor + len(preamble), b"_T_3")
    if operation1 != 1:
        raise ValueError("Expected opaque profile operation first")
    second_if, second_else_end = checked_else(body, first_end)
    operation2, fan_body, second_end = checked_if(body, second_if, b"_T_3")
    default_body, default_end = checked_else(body, second_end)
    if operation2 != 2 or body[default_body:default_end] != FAIL:
        raise ValueError("Unknown fan operation/default")
    if default_end != second_else_end or body[second_else_end:loop_end] != b"\xa5":
        raise ValueError("Unknown operation-chain tail")
    channels = decode_channel_tree(body[fan_body:second_end])
    return {"analysis_type": "Offline AML syntax, no firmware evaluation",
            "table_sha256": outer["sha256"], "method": "WMAX", "method_id": "0x15",
            "operation": 2, "channels": channels,
            "recognized_fan_reply": 0, "unknown_fan_reply": "0xffffffff",
            "limits": "Assignment targets only; Field definitions, EC firmware, RPM effects and safe boost range not established."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", type=Path, help="Saved DSDT file, not an EC interface")
    args = parser.parse_args()
    print(json.dumps(analyze(args.table.read_bytes()), indent=2))


if __name__ == "__main__":
    main()
