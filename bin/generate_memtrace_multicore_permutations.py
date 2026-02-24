#!/usr/bin/env python3
"""Generate 4-core memtrace run commands for random mixes and all permutations."""

from __future__ import annotations

import argparse
import csv
import itertools
import os
import random
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


TRACE_PATHS: List[str] = [
    "SCARAB_traces/datacenter/datacenter/clang/traces/simp/1270.zip",
    "SCARAB_traces/datacenter/datacenter/clang/traces/simp/2249.zip",
    "SCARAB_traces/datacenter/datacenter/clang/traces/simp/812.zip",
    "SCARAB_traces/datacenter/datacenter/gcc/traces/simp/1970.zip",
    "SCARAB_traces/datacenter/datacenter/gcc/traces/simp/907.zip",
    "SCARAB_traces/datacenter/datacenter/gcc/traces/simp/939.zip",
    "SCARAB_traces/datacenter/datacenter/mongodb/traces/simp/1362.zip",
    "SCARAB_traces/datacenter/datacenter/mongodb/traces/simp/4118.zip",
    "SCARAB_traces/datacenter/datacenter/mongodb/traces/simp/5198.zip",
    "SCARAB_traces/datacenter/datacenter/mysql/traces/simp/1172.zip",
    "SCARAB_traces/datacenter/datacenter/mysql/traces/simp/49.zip",
    "SCARAB_traces/datacenter/datacenter/postgres/traces/simp/2807.zip",
    "SCARAB_traces/datacenter/datacenter/postgres/traces/simp/5168.zip",
    "SCARAB_traces/datacenter/datacenter/postgres/traces/simp/5297.zip",
    "SCARAB_traces/datacenter/datacenter/verilator/traces/simp/23256.zip",
    "SCARAB_traces/datacenter/datacenter/verilator/traces/simp/24078.zip",
    "SCARAB_traces/datacenter/datacenter/verilator/traces/simp/31568.zip",
    "SCARAB_traces/datacenter/datacenter/xgboost/traces/simp/247.zip",
    "SCARAB_traces/datacenter/datacenter/xgboost/traces/simp/3311.zip",
    "SCARAB_traces/datacenter/datacenter/xgboost/traces/simp/463.zip",
    "SCARAB_traces/geekbench/single_core/clang/traces/simp/28.zip",
    "SCARAB_traces/geekbench/single_core/clang/traces/simp/966.zip",
    "SCARAB_traces/geekbench/single_core/file_compression/traces/simp/10037.zip",
    "SCARAB_traces/geekbench/single_core/file_compression/traces/simp/10503.zip",
    "SCARAB_traces/geekbench/single_core/file_compression/traces/simp/11232.zip",
    "SCARAB_traces/geekbench/single_core/html5_browser/traces/simp/1106.zip",
    "SCARAB_traces/geekbench/single_core/html5_browser/traces/simp/56.zip",
    "SCARAB_traces/geekbench/single_core/html5_browser/traces/simp/780.zip",
    "SCARAB_traces/geekbench/single_core/navigation/traces/simp/2096.zip",
    "SCARAB_traces/geekbench/single_core/navigation/traces/simp/3799.zip",
    "SCARAB_traces/geekbench/single_core/navigation/traces/simp/4190.zip",
    "SCARAB_traces/geekbench/single_core/photo_library/traces/simp/1827.zip",
    "SCARAB_traces/geekbench/single_core/photo_library/traces/simp/2806.zip",
    "SCARAB_traces/geekbench/single_core/photo_library/traces/simp/7.zip",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate random 4-core mixes from a fixed trace list and emit all "
            "core assignment permutations as scarab memtrace commands."
        )
    )
    parser.add_argument("--num-mixes", type=int, default=10, help="How many unique 4-trace mixes to sample.")
    parser.add_argument("--mix-size", type=int, default=4, help="Mix size (4 for 4-core experiments).")
    parser.add_argument("--seed", type=int, default=1, help="RNG seed for reproducible mix sampling.")
    parser.add_argument(
        "--trace-prefix",
        default="/home/iconst01",
        help="Prefix prepended to each relative trace path. Use empty string to keep as-is.",
    )
    parser.add_argument("--scarab-bin", default="./src/scarab", help="Path to scarab binary used in emitted commands.")
    parser.add_argument("--inst-limit", type=int, default=10_000_000, help="Value for --inst_limit.")
    parser.add_argument(
        "--extra-args",
        default="",
        help='Extra args appended to each command (example: "--warmup=10000000").',
    )
    parser.add_argument(
        "--output-prefix",
        default="AUTO_MIX4",
        help="Prefix used to build --output_dir names.",
    )
    parser.add_argument(
        "--script-out",
        default="generated_memtrace_mix4_runs.sh",
        help="Output shell script containing all generated commands.",
    )
    parser.add_argument(
        "--manifest-out",
        default="generated_memtrace_mix4_runs.csv",
        help="Output CSV mapping each command to mix/permutation/core assignment.",
    )
    return parser.parse_args()


def with_prefix(path: str, prefix: str) -> str:
    if os.path.isabs(path) or not prefix:
        return path
    return str(Path(prefix) / path)


def trace_tag(path: str) -> str:
    # Expected layout:
    # SCARAB_traces/<suite>/<subsuite>/<benchmark>/traces/simp/<id>.zip
    p = Path(path)
    trace_id = p.stem
    bench = p.parents[2].name
    suite = p.parts[1] if len(p.parts) > 1 else "trace"
    return f"{suite[:2]}_{bench}_{trace_id}"


def choose_mixes(traces: Sequence[str], mix_size: int, num_mixes: int, seed: int) -> List[Tuple[str, ...]]:
    all_mixes: List[Tuple[str, ...]] = list(itertools.combinations(traces, mix_size))
    if num_mixes > len(all_mixes):
        raise ValueError(
            f"Requested {num_mixes} mixes but only {len(all_mixes)} unique combinations exist "
            f"for mix size {mix_size} and {len(traces)} traces."
        )
    rng = random.Random(seed)
    return rng.sample(all_mixes, num_mixes)


def build_command(
    scarab_bin: str,
    perm: Sequence[str],
    inst_limit: int,
    output_dir: str,
    extra_args: str,
) -> str:
    cmd = [
        scarab_bin,
        "--frontend",
        "memtrace",
        "--num_cores=4",
        f"--cbp_trace_r0={perm[0]}",
        f"--cbp_trace_r1={perm[1]}",
        f"--cbp_trace_r2={perm[2]}",
        f"--cbp_trace_r3={perm[3]}",
        f"--inst_limit={inst_limit}",
        f"--output_dir={output_dir}",
    ]
    if extra_args.strip():
        cmd.append(extra_args.strip())
    return " ".join(cmd)


def write_outputs(
    script_path: Path,
    manifest_path: Path,
    commands: Iterable[str],
    rows: Iterable[Sequence[str]],
) -> None:
    script_path.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n\n" + "\n".join(commands) + "\n",
        encoding="utf-8",
    )
    os.chmod(script_path, 0o755)

    with manifest_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "mix_id",
                "perm_id",
                "output_dir",
                "core0",
                "core1",
                "core2",
                "core3",
                "command",
            ]
        )
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    if args.mix_size != 4:
        raise ValueError("This generator currently supports only 4-core mixes (use --mix-size=4).")
    if args.num_mixes <= 0:
        raise ValueError("--num-mixes must be > 0.")

    mixes = choose_mixes(TRACE_PATHS, args.mix_size, args.num_mixes, args.seed)

    commands: List[str] = []
    manifest_rows: List[List[str]] = []

    for mix_idx, mix in enumerate(mixes, start=1):
        perms = list(itertools.permutations(mix))
        for perm_idx, perm in enumerate(perms, start=1):
            perm_abs = tuple(with_prefix(p, args.trace_prefix) for p in perm)
            tags = [trace_tag(p) for p in perm]
            output_dir = (
                f"{args.output_prefix}_M{mix_idx:02d}_P{perm_idx:02d}_"
                f"C0_{tags[0]}_C1_{tags[1]}_C2_{tags[2]}_C3_{tags[3]}"
            )
            command = build_command(
                scarab_bin=args.scarab_bin,
                perm=perm_abs,
                inst_limit=args.inst_limit,
                output_dir=output_dir,
                extra_args=args.extra_args,
            )
            commands.append(command)
            manifest_rows.append(
                [
                    f"{mix_idx:02d}",
                    f"{perm_idx:02d}",
                    output_dir,
                    perm_abs[0],
                    perm_abs[1],
                    perm_abs[2],
                    perm_abs[3],
                    command,
                ]
            )

    script_out = Path(args.script_out)
    manifest_out = Path(args.manifest_out)
    write_outputs(script_out, manifest_out, commands, manifest_rows)

    print(f"Generated {len(mixes)} mixes x 24 permutations = {len(commands)} commands")
    print(f"Shell script: {script_out}")
    print(f"Manifest CSV: {manifest_out}")


if __name__ == "__main__":
    main()
