#!/usr/bin/env python3
"""Compare selected-PC memtrace off-path load VA histories between runs."""

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


REQUIRED = {
    "event_id", "event", "core", "pc", "onpath_observation", "map_version",
    "load_operand", "old_va", "va",
}
ONPATH_EVENTS = {"map_insert", "map_update", "onpath_observe"}


def read_trace(path):
    offpath_vas = Counter()
    offpath_contexts = defaultdict(Counter)
    onpath_contexts = {}
    event_counts = Counter()
    pcs = set()
    with Path(path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
            raise ValueError(f"{path}: not a selected-load event CSV; missing {sorted(REQUIRED - set(reader.fieldnames or []))}")
        for line, row in enumerate(reader, 2):
            event = row["event"]
            if event not in ONPATH_EVENTS and event != "offpath_generate":
                raise ValueError(f"{path}:{line}: unknown event {event!r}")
            pc = int(row["pc"], 0)
            pcs.add(pc)
            context = (
                int(row["core"]), pc, int(row["onpath_observation"]),
                int(row["map_version"]), int(row["load_operand"]),
            )
            va = int(row["va"], 0) if row["va"] else None
            event_counts[event] += 1
            if event == "offpath_generate":
                if va is None:
                    raise ValueError(f"{path}:{line}: missing off-path VA")
                offpath_vas[(context[0], context[1], context[4], va)] += 1
                offpath_contexts[context][va] += 1
            else:
                if context in onpath_contexts:
                    raise ValueError(f"{path}:{line}: duplicate on-path observation/operand")
                onpath_contexts[context] = va
    if len(pcs) != 1:
        raise ValueError(f"{path}: expected one selected PC, found {len(pcs)}")
    return {
        "pc": next(iter(pcs)), "offpath_vas": offpath_vas,
        "offpath_contexts": offpath_contexts, "onpath_contexts": onpath_contexts,
        "event_counts": event_counts,
    }


def context_fields(context):
    core, pc, observation, version, operand = context
    return [core, f"0x{pc:x}", observation, version, operand]


def compare(baseline, candidate):
    a, b = baseline["offpath_contexts"], candidate["offpath_contexts"]
    common = a.keys() & b.keys()
    changed_contexts = []
    for context in sorted(common):
        if set(a[context]) != set(b[context]):
            changed_contexts.append((context, a[context], b[context]))
    on_a, on_b = baseline["onpath_contexts"], candidate["onpath_contexts"]
    on_common = on_a.keys() & on_b.keys()
    return {
        "common_contexts": len(common),
        "changed_contexts": changed_contexts,
        "only_baseline_contexts": len(a.keys() - b.keys()),
        "only_candidate_contexts": len(b.keys() - a.keys()),
        "common_onpath_contexts": len(on_common),
        "changed_onpath_contexts": [key for key in sorted(on_common) if on_a[key] != on_b[key]],
        "only_baseline_onpath_contexts": len(on_a.keys() - on_b.keys()),
        "only_candidate_onpath_contexts": len(on_b.keys() - on_a.keys()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="ROB32 selected_load.csv")
    parser.add_argument("--candidate", required=True, help="ROB512 selected_load.csv")
    parser.add_argument("--output-prefix", help="Optional prefix for detailed comparison CSVs")
    args = parser.parse_args()
    baseline, candidate = read_trace(args.baseline), read_trace(args.candidate)
    if baseline["pc"] != candidate["pc"]:
        parser.error("the two CSVs profile different PCs")
    result = compare(baseline, candidate)
    av, bv = baseline["offpath_vas"], candidate["offpath_vas"]
    print(f"selected PC: 0x{baseline['pc']:x}")
    print(f"off-path load operands: baseline={sum(av.values())} candidate={sum(bv.values())}")
    print(f"unique core/PC/operand/VA keys: baseline={len(av)} candidate={len(bv)}")
    print(f"common VA keys: {len(av.keys() & bv.keys())}")
    print(f"VA keys only baseline: {len(av.keys() - bv.keys())}")
    print(f"VA keys only candidate: {len(bv.keys() - av.keys())}")
    print(f"common off-path contexts: {result['common_contexts']}")
    print(f"common contexts with different reused VA: {len(result['changed_contexts'])}")
    print(f"contexts only baseline/candidate: {result['only_baseline_contexts']}/{result['only_candidate_contexts']}")
    print(f"common on-path contexts: {result['common_onpath_contexts']}")
    print(f"common on-path contexts with different saved VA: {len(result['changed_onpath_contexts'])}")
    print(f"on-path contexts only baseline/candidate: {result['only_baseline_onpath_contexts']}/{result['only_candidate_onpath_contexts']}")
    for context, left, right in result["changed_contexts"][:10]:
        print(f"  changed {context_fields(context)}: {sorted(hex(x) for x in left)} -> {sorted(hex(x) for x in right)}")
    print("Different totals, cycles, or one-run-only contexts do not by themselves prove a changed reused VA for the same speculative episode.")

    if args.output_prefix:
        prefix = Path(args.output_prefix)
        with Path(f"{prefix}.vas.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["core", "pc", "load_operand", "va", "baseline_count", "candidate_count", "status"])
            for core, pc, operand, va in sorted(av.keys() | bv.keys()):
                key = (core, pc, operand, va)
                status = "common" if key in av and key in bv else ("only_baseline" if key in av else "only_candidate")
                writer.writerow([core, f"0x{pc:x}", operand, f"0x{va:x}", av[key], bv[key], status])
        with Path(f"{prefix}.contexts.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["core", "pc", "onpath_observation", "map_version", "load_operand",
                             "baseline_vas", "candidate_vas", "baseline_count", "candidate_count", "status"])
            for context in sorted(baseline["offpath_contexts"].keys() | candidate["offpath_contexts"].keys()):
                left = baseline["offpath_contexts"].get(context, Counter())
                right = candidate["offpath_contexts"].get(context, Counter())
                status = "common_same_va" if set(left) == set(right) else (
                    "common_different_va" if left and right else ("only_baseline" if left else "only_candidate"))
                writer.writerow(context_fields(context) + [
                    ";".join(f"0x{x:x}" for x in sorted(left)),
                    ";".join(f"0x{x:x}" for x in sorted(right)),
                    sum(left.values()), sum(right.values()), status,
                ])
        with Path(f"{prefix}.onpath.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["core", "pc", "onpath_observation", "map_version", "load_operand",
                             "baseline_va", "candidate_va", "status"])
            on_a, on_b = baseline["onpath_contexts"], candidate["onpath_contexts"]
            for context in sorted(on_a.keys() | on_b.keys()):
                left, right = on_a.get(context), on_b.get(context)
                status = "common_same_va" if context in on_a and context in on_b and left == right else (
                    "common_different_va" if context in on_a and context in on_b else (
                        "only_baseline" if context in on_a else "only_candidate"))
                writer.writerow(context_fields(context) + [
                    f"0x{left:x}" if left is not None else "",
                    f"0x{right:x}" if right is not None else "", status,
                ])
        print(f"wrote: {prefix}.vas.csv, {prefix}.contexts.csv, and {prefix}.onpath.csv")


if __name__ == "__main__":
    main()
