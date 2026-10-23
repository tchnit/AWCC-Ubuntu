#!/usr/bin/python3
"""Strict, offline x17 WMAX dispatch decoder, NOT an ACPI interpreter.

Only parses copied AML bytes. Refuses layouts it cannot prove; does not access
sysfs, evaluate firmware methods, or read/write EC registers. Method branch
bodies are deliberately opaque. See ACPI 6.5 section 20 (AML grammar).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import uuid


def pkg(data: bytes, offset: int) -> tuple[int, int]:
    if not 0 <= offset < len(data):
        raise ValueError("PkgLength offset outside input")
    lead = data[offset]
    following = lead >> 6
    if following and lead & 0x30:
        raise ValueError("Reserved PkgLength bits set")
    if offset + following >= len(data):
        raise ValueError("Truncated PkgLength")
    length = lead & (0x0F if following else 0x3F)
    for index in range(following):
        length |= data[offset + 1 + index] << (4 + 8 * index)
    body, end = offset + following + 1, offset + length
    if not body <= end <= len(data):
        raise ValueError("Invalid package bounds")
    return body, end


def integer(data: bytes, offset: int) -> tuple[int, int]:
    if not 0 <= offset < len(data):
        raise ValueError("Integer offset outside input")
    opcode = data[offset]
    if opcode in (0, 1, 0xFF):
        return {0: 0, 1: 1, 0xFF: 0xFFFFFFFFFFFFFFFF}[opcode], offset + 1
    sizes = {0x0A: 1, 0x0B: 2, 0x0C: 4, 0x0E: 8}
    if opcode not in sizes:
        raise ValueError(f"Expected integer at {offset:#x}")
    end = offset + 1 + sizes[opcode]
    if end > len(data):
        raise ValueError("Truncated integer")
    return int.from_bytes(data[offset + 1:end], "little"), end


def chain(data: bytes, start: int, end: int) -> tuple[list[dict], dict, int]:
    if data[start] != 0xA0:
        raise ValueError("Expected If in selector chain")
    predicate, if_end = pkg(data, start + 1)
    if data[predicate:predicate + 5] != b"\x93_T_0":
        raise ValueError("Selector predicate is not LEqual(_T_0, integer)")
    method_id, branch_start = integer(data, predicate + 5)
    if branch_start > if_end:
        raise ValueError("Predicate outside If bounds")
    branch = {"method_id": hex(method_id), "if_offset": hex(start),
              "body_start": hex(branch_start), "body_end": hex(if_end)}
    if if_end >= end or data[if_end] != 0xA1:
        raise ValueError("Missing Else in dispatch chain")
    else_start, else_end = pkg(data, if_end + 1)
    if else_end > end:
        raise ValueError("Else outside dispatch bounds")
    if data[else_start] == 0xA0:
        branches, default, consumed = chain(data, else_start, else_end)
        if consumed != else_end:
            raise ValueError("Unhandled terms after nested If/Else")
        return [branch] + branches, default, else_end
    # Store(DWord(0xffffffff), Local0); Break. No external method invocation.
    if data[else_start:else_end] != b"\x70\x0c\xff\xff\xff\xff\x60\xa5":
        raise ValueError("Unknown default-branch semantics")
    return [branch], {"offset": hex(else_start), "store_local0": "0xffffffff",
                     "break": True, "raw": data[else_start:else_end].hex()}, else_end


def analyze(data: bytes) -> dict:
    if len(data) < 36 or data[:4] != b"DSDT":
        raise ValueError("Expected DSDT table")
    if struct.unpack_from("<I", data, 4)[0] != len(data) or sum(data) & 0xFF:
        raise ValueError("Table length/checksum mismatch")
    # This deliberately recognizes only the observed AMW1 device layout.
    candidates = []
    for offset in range(36, len(data) - 8):
        if data[offset:offset + 2] != b"\x5b\x82":
            continue
        try:
            body, end = pkg(data, offset + 2)
            if data[body:body + 4] == b"AMW1":
                candidates.append((body, end))
        except ValueError:
            continue
    if len(candidates) != 1:
        raise ValueError("AMW1 device is absent or ambiguous")
    device_start, device_end = candidates[0]
    wdg = data.find(b"\x08_WDG\x11", device_start, device_end)
    if wdg < 0:
        raise ValueError("Missing static _WDG buffer")
    buffer_start, buffer_end = pkg(data, wdg + 6)
    buffer_size, contents = integer(data, buffer_start)
    if contents + buffer_size != buffer_end or buffer_size % 20:
        raise ValueError("Unexpected _WDG size/layout")
    records = []
    for offset in range(contents, buffer_end, 20):
        raw = data[offset:offset + 20]
        records.append({"guid": str(uuid.UUID(bytes_le=raw[:16])).upper(),
                        "object_id": raw[16:18].decode("ascii"),
                        "instances": raw[18], "flags": hex(raw[19])})
    awcc = [r for r in records if r["guid"] == "A70591CE-A997-11DA-B012-B622A1EF5492"]
    if len(awcc) != 1 or awcc[0]["object_id"] != "AX" or awcc[0]["flags"] != "0x2":
        raise ValueError("_WDG does not map AWCC GUID to method WMAX")

    methods = []
    for offset in range(device_start, device_end - 8):
        if data[offset] != 0x14:
            continue
        try:
            body, end = pkg(data, offset + 1)
            if end <= device_end and data[body:body + 4] == b"WMAX":
                methods.append((offset, body + 4, end))
        except ValueError:
            continue
    if len(methods) != 1:
        raise ValueError("WMAX method is absent or ambiguous")
    method_offset, cursor, method_end = methods[0]
    flags = data[cursor]
    if flags != 0x0B:  # Serialized, three arguments, sync level 0.
        raise ValueError("Unexpected WMAX MethodFlags")
    cursor += 1
    # Validate all pre-dispatch terms, not just a substring for method ID 0x25.
    preamble = b"".join(b"\x08_T_" + str(i).encode() + b"\x00" for i in range(8, -1, -1))
    preamble += b"\x70\x68DMR0\x70\x69DMR1\x70\x6aDMR2\x70\x00DMRR"
    preamble += b"\x8c\x6a\x00DM20\x8c\x6a\x01DM21\x8c\x6a\x0a\x02DM22\x8c\x6a\x0a\x03DM23"
    preamble += b"\x70\x00\x60"  # Store Zero, Local0.
    if data[cursor:cursor + len(preamble)] != preamble:
        raise ValueError("Unknown WMAX preamble; cannot prove selector origin")
    cursor += len(preamble)
    if data[cursor] != 0xA2:
        raise ValueError("Missing dispatch While")
    loop_start, loop_end = pkg(data, cursor + 1)
    selector = b"\x01\x70DMR1_T_0"  # While(One), Store Arg1-derived DMR1 to selector.
    if data[loop_start:loop_start + len(selector)] != selector:
        raise ValueError("Unknown method selector source")
    branches, default, consumed = chain(data, loop_start + len(selector), loop_end)
    if data[consumed:loop_end] != b"\xa5" or data[loop_end:method_end] != b"\xa4\x60":
        raise ValueError("Unknown post-dispatch control flow")
    ids = [int(branch["method_id"], 16) for branch in branches]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate selector case")
    return {
        "sha256": hashlib.sha256(data).hexdigest(), "table_length": len(data),
        "wdg": records, "method": "WMAX", "method_offset": hex(method_offset),
        "method_end": hex(method_end), "argument_count": flags & 7, "serialized": True,
        "selector": "Arg1 -> DMR1 -> _T_0", "branches": branches,
        "default": default, "game_shift_0x25_present": 0x25 in ids,
        "absent_method_result": "Local0 = 0xffffffff; Break; Return(Local0)",
        "limits": "Offline static dispatch only; branch bodies and EC behavior not evaluated.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", type=Path, help="Copied DSDT file, never a live method interface")
    args = parser.parse_args()
    print(json.dumps(analyze(args.table.read_bytes()), indent=2))


if __name__ == "__main__":
    main()
