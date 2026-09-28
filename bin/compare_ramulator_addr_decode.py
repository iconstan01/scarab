#!/usr/bin/env python3
"""Compare PA-to-DRAM decoding, ignoring request order and access counts.

Inputs must have the same workload-to-core placement and DRAM configuration.
This compares observed decoding; it does not establish that decoding is correct.
"""

import argparse
import csv
from pathlib import Path


def aggregate_rows(rows):
    mappings = {}
    for row in rows:
        key = (int(row["core_id"]), int(row["transaction_address"], 16))
        current = mappings.setdefault(key, {"tuples": set(), "accesses": 0})
        current["tuples"].add(tuple(int(part) for part in row["decoded_tuple"].split(":")))
        current["accesses"] += 1
    return mappings


def aggregate(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        required = {"core_id", "transaction_address", "decoded_tuple"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"{path}: missing required fields {sorted(required)}")
        return aggregate_rows(reader)


def summarize(baseline, candidate, core_id=None):
    a = {key for key in baseline if core_id is None or key[0] == core_id}
    b = {key for key in candidate if core_id is None or key[0] == core_id}
    common = a & b
    different = sum(baseline[key]["tuples"] != candidate[key]["tuples"] for key in common)
    return {
        "core_id": "all" if core_id is None else core_id,
        "baseline_transactions": len(a),
        "candidate_transactions": len(b),
        "common_keys": len(common),
        "different_tuple_sets": different,
        "different_common_pct": 100.0 * different / len(common) if common else None,
        "only_baseline": len(a - b),
        "only_candidate": len(b - a),
        "baseline_multi_tuple_keys": sum(len(baseline[key]["tuples"]) > 1 for key in a),
        "candidate_multi_tuple_keys": sum(len(candidate[key]["tuples"]) > 1 for key in b),
        "baseline_accesses": sum(baseline[key]["accesses"] for key in a),
        "candidate_accesses": sum(candidate[key]["accesses"] for key in b),
    }


def tuple_text(value):
    return ";".join(":".join(map(str, item)) for item in sorted(value["tuples"])) if value else ""


def write_comparison(path, baseline, candidate):
    fields = ["core_id", "transaction_address", "status", "baseline_tuples", "candidate_tuples",
              "baseline_accesses", "candidate_accesses"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for key in sorted(baseline.keys() | candidate.keys()):
            a = baseline.get(key)
            b = candidate.get(key)
            if a is None:
                status = "only_candidate"
            elif b is None:
                status = "only_baseline"
            else:
                status = "same" if a["tuples"] == b["tuples"] else "different"
            writer.writerow({
                "core_id": key[0], "transaction_address": f"0x{key[1]:016x}", "status": status,
                "baseline_tuples": tuple_text(a), "candidate_tuples": tuple_text(b),
                "baseline_accesses": a["accesses"] if a else "",
                "candidate_accesses": b["accesses"] if b else "",
            })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()
    baseline = aggregate(args.baseline)
    candidate = aggregate(args.candidate)
    overall = summarize(baseline, candidate)
    cores = sorted({key[0] for key in baseline.keys() | candidate.keys()})
    summaries = [overall] + [summarize(baseline, candidate, core) for core in cores]
    prefix = Path(args.output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    comparison_path = Path(str(prefix) + ".comparison.csv")
    summary_path = Path(str(prefix) + ".summary.csv")
    write_comparison(comparison_path, baseline, candidate)
    with summary_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(overall))
        writer.writeheader()
        writer.writerows(summaries)
    for name, value in overall.items():
        if name == "different_common_pct":
            value = "n/a (no common keys)" if value is None else f"{value:.4f}%"
        if name != "core_id":
            print(f"{name}: {value}")
    print(f"wrote: {comparison_path}")
    print(f"wrote: {summary_path}")
    print("Access counts and one-run-only addresses are traffic differences, not changed decoding.")


if __name__ == "__main__":
    main()
