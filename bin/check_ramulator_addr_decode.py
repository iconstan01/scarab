#!/usr/bin/env python3
"""Check whether distinct DRAM transactions decode to the same Ramulator tuple."""

import argparse
import csv
from collections import Counter


def analyze(path, max_examples):
    seen = {}
    examples = []
    counts = Counter()
    max_row_bits = 0
    max_row = None

    with open(path, newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            counts["requests"] += 1
            bits = int(row["row_input_bits"])
            decoded_row = int(row["row"])
            configured_rows = int(row["configured_rows"])
            max_row_bits = max(max_row_bits, bits)
            max_row = decoded_row if max_row is None else max(max_row, decoded_row)
            if bits >= 32:
                counts["wide_row_inputs"] += 1
            if decoded_row < 0 or decoded_row >= configured_rows:
                counts["out_of_range_rows"] += 1

            transaction = int(row["transaction_address"], 16)
            key = row["decoded_tuple"]
            previous = seen.setdefault(key, transaction)
            if previous != transaction:
                counts["collision_requests"] += 1
                if len(examples) < max_examples:
                    examples.append((key, previous, transaction))

    print(f"accepted requests: {counts['requests']}")
    print(f"distinct decoded tuples: {len(seen)}")
    print(f"maximum row input width: {max_row_bits} bits")
    print(f"requests with row input width >= 32: {counts['wide_row_inputs']}")
    print(f"maximum decoded row: {max_row}")
    print(f"requests with row outside configured range: {counts['out_of_range_rows']}")
    print(f"requests with a tuple previously used by another transaction: {counts['collision_requests']}")
    for key, first, later in examples:
        print(f"  tuple={key} first=0x{first:016x} later=0x{later:016x}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", help="CSV from --ramulator_addr_decode_trace_file")
    parser.add_argument("--max-examples", type=int, default=10)
    args = parser.parse_args()
    analyze(args.trace, args.max_examples)


if __name__ == "__main__":
    main()
