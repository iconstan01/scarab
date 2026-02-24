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
        "--tcsh-switch-out",
        default="generated_memtrace_mix4_cases.tcsh",
        help="Output tcsh switch($bcode) script compatible with Slurm launcher style.",
    )
    parser.add_argument(
        "--no-tcsh-switch",
        action="store_true",
        help="Do not generate the tcsh switch script.",
    )
    parser.add_argument(
        "--manifest-out",
        default="generated_memtrace_mix4_runs.csv",
        help="Output CSV mapping each command to mix/permutation/core assignment.",
    )
    parser.add_argument(
        "--tcsh-exec-cmd",
        default="$exec_path/$executable",
        help="Executable expression used in generated tcsh cases.",
    )
    parser.add_argument(
        "--tcsh-extra-options",
        default="$EXTRA_OPTIONS",
        help="Extra options expression used in generated tcsh cases.",
    )
    parser.add_argument(
        "--tcsh-outdir-var",
        default="$outdir",
        help="Output directory expression used in generated tcsh cases.",
    )
    parser.add_argument(
        "--tcsh-params-file",
        default="$exec_path/PARAMS.golden_cove",
        help="PARAMS file expression copied into each generated tcsh run directory.",
    )
    parser.add_argument(
        "--tcsh-include-inst-limit",
        action="store_true",
        help="Also include --inst_limit in tcsh cases (normally supplied via $EXTRA_OPTIONS).",
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


def build_tcsh_case_command(
    tcsh_exec_cmd: str,
    perm: Sequence[str],
    run_name: str,
    tcsh_outdir_var: str,
    tcsh_extra_options: str,
    inst_limit: int,
    include_inst_limit: bool,
) -> str:
    cmd = [
        tcsh_exec_cmd,
        "--frontend",
        "memtrace",
        "--num_cores=4",
        f"--cbp_trace_r0={perm[0]}",
        f"--cbp_trace_r1={perm[1]}",
        f"--cbp_trace_r2={perm[2]}",
        f"--cbp_trace_r3={perm[3]}",
    ]
    if include_inst_limit:
        cmd.append(f"--inst_limit={inst_limit}")
    if tcsh_extra_options.strip():
        cmd.append(tcsh_extra_options.strip())
    cmd.append(f"--output_dir={tcsh_outdir_var}/{run_name}.dir")
    return " ".join(cmd) + f" >& {tcsh_outdir_var}/{run_name}.out"


def build_tcsh_case_block(
    bcode: int,
    run_name: str,
    case_command: str,
    tcsh_outdir_var: str,
    tcsh_params_file: str,
) -> str:
    lines = [
        f"case {bcode}:",
        f"mkdir -p {tcsh_outdir_var}/{run_name}.dir",
        f"cd {tcsh_outdir_var}/{run_name}.dir",
        f"cp {tcsh_params_file} PARAMS.in",
        case_command,
        "breaksw",
    ]
    return "\n".join(lines)


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
                "bcode",
                "mix_id",
                "perm_id",
                "run_name",
                "core0",
                "core1",
                "core2",
                "core3",
                "bash_command",
                "tcsh_case_command",
            ]
        )
        writer.writerows(rows)


def write_tcsh_switch(tcsh_path: Path, case_blocks: Sequence[str]) -> None:
    lines: List[str] = [
        "#!/bin/tcsh",
        "# Auto-generated switch cases for memtrace multicore permutation runs.",
        "# Usage: set bcode=<case_id>; then execute this script body in your launcher.",
        "",
        "switch($bcode)",
    ]
    lines.extend(case_blocks)
    lines.extend(
        [
            "default:",
            'echo "Unknown bcode: $bcode"',
            "exit 1",
            "breaksw",
            "endsw",
            "",
        ]
    )
    tcsh_path.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(tcsh_path, 0o755)


def main() -> None:
    args = parse_args()
    if args.mix_size != 4:
        raise ValueError("This generator currently supports only 4-core mixes (use --mix-size=4).")
    if args.num_mixes <= 0:
        raise ValueError("--num-mixes must be > 0.")

    mixes = choose_mixes(TRACE_PATHS, args.mix_size, args.num_mixes, args.seed)

    commands: List[str] = []
    manifest_rows: List[List[str]] = []
    tcsh_case_blocks: List[str] = []
    bcode = 1

    for mix_idx, mix in enumerate(mixes, start=1):
        perms = list(itertools.permutations(mix))
        for perm_idx, perm in enumerate(perms, start=1):
            perm_abs = tuple(with_prefix(p, args.trace_prefix) for p in perm)
            tags = [trace_tag(p) for p in perm]
            run_name = (
                f"{args.output_prefix}_M{mix_idx:02d}_P{perm_idx:02d}_"
                f"C0_{tags[0]}_C1_{tags[1]}_C2_{tags[2]}_C3_{tags[3]}"
            )
            bash_command = build_command(
                scarab_bin=args.scarab_bin,
                perm=perm_abs,
                inst_limit=args.inst_limit,
                output_dir=run_name,
                extra_args=args.extra_args,
            )
            tcsh_case_command = build_tcsh_case_command(
                tcsh_exec_cmd=args.tcsh_exec_cmd,
                perm=perm_abs,
                run_name=run_name,
                tcsh_outdir_var=args.tcsh_outdir_var,
                tcsh_extra_options=args.tcsh_extra_options,
                inst_limit=args.inst_limit,
                include_inst_limit=args.tcsh_include_inst_limit,
            )
            tcsh_case_blocks.append(
                build_tcsh_case_block(
                    bcode=bcode,
                    run_name=run_name,
                    case_command=tcsh_case_command,
                    tcsh_outdir_var=args.tcsh_outdir_var,
                    tcsh_params_file=args.tcsh_params_file,
                )
            )
            commands.append(bash_command)
            manifest_rows.append(
                [
                    str(bcode),
                    f"{mix_idx:02d}",
                    f"{perm_idx:02d}",
                    run_name,
                    perm_abs[0],
                    perm_abs[1],
                    perm_abs[2],
                    perm_abs[3],
                    bash_command,
                    tcsh_case_command,
                ]
            )
            bcode += 1

    script_out = Path(args.script_out)
    manifest_out = Path(args.manifest_out)
    write_outputs(script_out, manifest_out, commands, manifest_rows)
    if not args.no_tcsh_switch:
        write_tcsh_switch(Path(args.tcsh_switch_out), tcsh_case_blocks)

    print(f"Generated {len(mixes)} mixes x 24 permutations = {len(commands)} commands")
    print(f"Shell script: {script_out}")
    if not args.no_tcsh_switch:
        print(f"tcsh switch script: {args.tcsh_switch_out}")
    print(f"Manifest CSV: {manifest_out}")


if __name__ == "__main__":
    main()
