#!/usr/bin/env python3
# Pad an Intel HEX file so its last 128-byte block is complete.
# Usage: python pad_hex.py <file.hex>

import sys
import os

BLOCK = 128


def parse_hex(path):
    lines = [l.strip() for l in open(path, "r", encoding="ascii") if l.strip()]
    base = 0
    max_addr = -1
    for line in lines:
        if not line.startswith(":") or len(line) < 11:
            continue
        n = int(line[1:3], 16)
        addr = int(line[3:7], 16)
        typ = int(line[7:9], 16)
        if typ == 0x04:
            base = int(line[9:13], 16) << 16
        elif typ == 0x00:
            max_addr = max(max_addr, base + addr + n - 1)
    return lines, max_addr


def make_record(addr, data):
    rec = [len(data), (addr >> 8) & 0xFF, addr & 0xFF, 0x00] + list(data)
    chk = (-sum(rec)) & 0xFF
    return ":" + "".join("%02X" % b for b in rec) + "%02X" % chk


def main():
    if len(sys.argv) != 2:
        print("[pad_hex] usage: pad_hex.py <file.hex>")
        return 1

    path = sys.argv[1]
    if not os.path.exists(path):
        print("[pad_hex] not found:", path)
        return 1

    lines, max_addr = parse_hex(path)
    if max_addr < 0:
        print("[pad_hex] no data records")
        return 1

    end = max_addr + 1
    aligned_end = ((end + BLOCK - 1) // BLOCK) * BLOCK
    pad_len = aligned_end - end

    if pad_len == 0:
        print("[pad_hex] already aligned: end=0x%X" % end)
        return 0

    if end > 0xFFFF:
        print("[pad_hex] end above 64K, manual handling needed")
        return 1

    record = make_record(end, [0xFF] * pad_len)

    out = []
    inserted = False
    for line in lines:
        if line.upper() == ":00000001FF":
            out.append(record)
            inserted = True
        out.append(line)

    if not inserted:
        out.append(record)
        out.append(":00000001FF")

    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(out) + "\n")

    print("[pad_hex] padded 0x%X..0x%X with %d bytes" %
          (end, aligned_end - 1, pad_len))
    return 0


if __name__ == "__main__":
    sys.exit(main())
