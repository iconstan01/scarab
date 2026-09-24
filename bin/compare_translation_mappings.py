#!/usr/bin/env python3
"""Aggregate Scarab translation-event CSVs and compare VPN-to-PFN results."""

import argparse
import csv
from collections import defaultdict
from pathlib import Path


KEY_FIELDS = ("trace_id", "pid", "vpn")
MAPPING_FIELDS = [
    "trace_id", "pid", "vpn", "first_pfn", "last_pfn", "pfns_observed",
    "pfn_transition_count", "pfn_transition_sequence", "observation_count", "first_phase", "first_roi_id",
    "first_sim_time", "first_cycle", "first_committed_insts", "last_phase",
    "last_roi_id", "last_sim_time", "last_cycle", "last_committed_insts",
    "cores_observed", "phases_observed",
]


def aggregate(path):
    mappings = {}
    with Path(path).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            key = tuple(row[field].lower() for field in KEY_FIELDS)
            pfn = row["pfn"].lower()
            current = mappings.get(key)
            if current is None:
                current = {
                    "first": row,
                    "last": row,
                    "pfns": set(),
                    "transitions": 0,
                    "transition_pfns": [],
                    "observations": 0,
                    "cores": set(),
                    "phases": set(),
                }
                mappings[key] = current
            elif current["last"]["pfn"].lower() != pfn:
                current["transitions"] += 1
                current["transition_pfns"].append(pfn)
            current["last"] = row
            current["pfns"].add(pfn)
            current["observations"] += 1
            current["cores"].add(row["sim_core"])
            current["phases"].add(row["phase"])
    return mappings


def mapping_row(key, value):
    first = value["first"]
    last = value["last"]
    return {
        "trace_id": key[0],
        "pid": key[1],
        "vpn": key[2],
        "first_pfn": first["pfn"],
        "last_pfn": last["pfn"],
        "pfns_observed": ";".join(sorted(value["pfns"])),
        "pfn_transition_count": value["transitions"],
        "pfn_transition_sequence": ";".join(value["transition_pfns"]),
        "observation_count": value["observations"],
        "first_phase": first["phase"],
        "first_roi_id": first["roi_id"],
        "first_sim_time": first["sim_time"],
        "first_cycle": first["cycle"],
        "first_committed_insts": first["committed_insts"],
        "last_phase": last["phase"],
        "last_roi_id": last["roi_id"],
        "last_sim_time": last["sim_time"],
        "last_cycle": last["cycle"],
        "last_committed_insts": last["committed_insts"],
        "cores_observed": ";".join(sorted(value["cores"], key=int)),
        "phases_observed": ";".join(sorted(value["phases"])),
    }


def write_csv(path, rows, fields):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=("Input rows may be memory-request observations or committed load/store "
                "observations. Compare like-for-like CSVs and use a unique output file "
                "for each simulation."),
    )
    parser.add_argument("--baseline", required=True, help="Baseline translation-event CSV")
    parser.add_argument("--candidate", required=True, help="Candidate translation-event CSV")
    parser.add_argument("--output-prefix", required=True, help="Prefix for generated comparison CSVs")
    args = parser.parse_args()

    baseline = aggregate(args.baseline)
    candidate = aggregate(args.candidate)
    prefix = Path(args.output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    baseline_rows = [mapping_row(key, value) for key, value in sorted(baseline.items())]
    candidate_rows = [mapping_row(key, value) for key, value in sorted(candidate.items())]
    write_csv(f"{prefix}.baseline_mappings.csv", baseline_rows, MAPPING_FIELDS)
    write_csv(f"{prefix}.candidate_mappings.csv", candidate_rows, MAPPING_FIELDS)

    comparison = []
    by_space = defaultdict(lambda: {"baseline": 0, "candidate": 0, "common": 0, "different": 0,
                                    "transition_pattern_different": 0,
                                    "only_baseline": 0, "only_candidate": 0})
    common = different = transition_pattern_different = only_baseline = only_candidate = 0
    for key in sorted(set(baseline) | set(candidate)):
        left = baseline.get(key)
        right = candidate.get(key)
        space = (key[0], key[1])
        group = by_space[space]
        group["baseline"] += left is not None
        group["candidate"] += right is not None
        if left is None:
            status = "only_candidate"
            only_candidate += 1
            group["only_candidate"] += 1
        elif right is None:
            status = "only_baseline"
            only_baseline += 1
            group["only_baseline"] += 1
        else:
            common += 1
            group["common"] += 1
            changed = (left["pfns"] != right["pfns"] or
                       left["first"]["pfn"].lower() != right["first"]["pfn"].lower() or
                       left["last"]["pfn"].lower() != right["last"]["pfn"].lower())
            transition_diff = left["transition_pfns"] != right["transition_pfns"]
            if transition_diff:
                transition_pattern_different += 1
                group["transition_pattern_different"] += 1
            status = ("different_pfn" if changed else
                      "different_transition_pattern" if transition_diff else "same_mapping_behavior")
            if changed:
                different += 1
                group["different"] += 1
        comparison.append({
            "trace_id": key[0], "pid": key[1], "vpn": key[2], "status": status,
            "baseline_pfns": ";".join(sorted(left["pfns"])) if left else "",
            "candidate_pfns": ";".join(sorted(right["pfns"])) if right else "",
            "baseline_transitions": left["transitions"] if left else "",
            "candidate_transitions": right["transitions"] if right else "",
            "baseline_transition_pfns": ";".join(left["transition_pfns"]) if left else "",
            "candidate_transition_pfns": ";".join(right["transition_pfns"]) if right else "",
        })
    write_csv(f"{prefix}.comparison.csv", comparison,
              ["trace_id", "pid", "vpn", "status", "baseline_pfns", "candidate_pfns",
               "baseline_transitions", "candidate_transitions", "baseline_transition_pfns",
               "candidate_transition_pfns"])

    grouped_rows = []
    for (trace_id, pid), counts in sorted(by_space.items()):
        changed_pct = 100.0 * counts["different"] / counts["common"] if counts["common"] else 0.0
        grouped_rows.append({"trace_id": trace_id, "pid": pid, **counts,
                             "common_pfns_different_pct": f"{changed_pct:.6f}"})
    write_csv(f"{prefix}.by_address_space.csv", grouped_rows,
              ["trace_id", "pid", "baseline", "candidate", "common", "different",
               "transition_pattern_different", "only_baseline", "only_candidate",
               "common_pfns_different_pct"])

    changed_pct = 100.0 * different / common if common else 0.0
    summary = [{"baseline_mappings": len(baseline), "candidate_mappings": len(candidate),
                "common_keys": common, "different_pfns": different, "only_baseline": only_baseline,
                "only_candidate": only_candidate,
                "transition_pattern_different": transition_pattern_different,
                "common_pfns_different_pct": f"{changed_pct:.6f}"}]
    write_csv(f"{prefix}.summary.csv", summary, list(summary[0].keys()))
    print(f"baseline mappings: {len(baseline)}")
    print(f"candidate mappings: {len(candidate)}")
    print(f"common keys: {common}")
    print(f"different PFN mappings: {different}")
    print(f"different within-run transition patterns: {transition_pattern_different}")
    print(f"only baseline: {only_baseline}")
    print(f"only candidate: {only_candidate}")
    print(f"common mappings with different PFNs: {changed_pct:.4f}%")
    print(f"wrote comparison CSVs with prefix: {prefix}")


if __name__ == "__main__":
    main()
