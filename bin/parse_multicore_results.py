#!/usr/bin/env python3
"""Fast manifest-driven Scarab multicore parser.

Compatible with the existing YAML style:
- experiments: {name: {root_dir: ...}}
- manifest_path
- output_file
- stats: {alias: SCARAB_STAT_NAME}
- metrics: {metric_name: pandas-eval-formula}

Main speedups vs the original script:
- parallel parsing across run directories (`--workers`)
- faster manifest iteration (itertuples, no iterrows)
- targeted stat parsing (only requested stat names + IPC)
"""

from __future__ import annotations

import argparse
import os
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

try:
    import pandas as pd
except ModuleNotFoundError:
    pd = None

try:
    import yaml
except ModuleNotFoundError:
    yaml = None


STAT_FILE_RE = re.compile(r"\.stat\.(\d+)\.out$")
STAT_NAME_RE = re.compile(r"^[A-Z0-9_]+$")
IPC_RE = re.compile(r"IPC:\s*([^\s]+)")


def extract_benchmark_name(full_path_str: str) -> str:
    try:
        p = Path(full_path_str)
        return p.parents[2].name
    except Exception:
        return "unknown"


def normalize_trace_path(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value)


def resolve_run_dir(root_dir: Path, run_name: str) -> Tuple[Path, bool]:
    p1 = root_dir / f"{run_name}.dir"
    if p1.exists():
        return p1, True
    p2 = root_dir / run_name
    return p2, p2.exists()


def parse_run_stats(
    run_dir: Path,
    core_ids: Sequence[int],
    needed_real_stats: Sequence[str],
) -> Dict[int, Dict[str, float]]:
    out: Dict[int, Dict[str, float]] = {cid: {} for cid in core_ids}
    if not run_dir.exists():
        return out

    wanted = set(needed_real_stats)
    want_ipc = "IPC" in wanted
    wanted.discard("IPC")

    for file_path in run_dir.glob("*.stat.*.out"):
        m = STAT_FILE_RE.search(file_path.name)
        if not m:
            continue
        core_id = int(m.group(1))
        if core_id not in out:
            continue

        with file_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    stat_name = parts[0]
                    if stat_name in wanted and STAT_NAME_RE.fullmatch(stat_name):
                        try:
                            out[core_id][stat_name] = float(parts[1])
                        except ValueError:
                            pass

                if want_ipc and "IPC:" in line and "Cumulative:" in line:
                    m_ipc = IPC_RE.search(line)
                    if m_ipc:
                        try:
                            out[core_id]["IPC"] = float(m_ipc.group(1))
                        except ValueError:
                            pass

    return out


def parse_one_task(task: Tuple) -> List[dict]:
    (
        exp_name,
        root_dir_str,
        run_name,
        mix_id,
        perm_id,
        core_trace_pairs,
        stats_items,
        core_ids,
        needed_real_stats,
    ) = task

    root_dir = Path(root_dir_str)
    run_dir, _exists = resolve_run_dir(root_dir, run_name)
    core_stats = parse_run_stats(run_dir, core_ids, needed_real_stats)

    records: List[dict] = []
    for core_id, trace_path in core_trace_pairs:
        trace_path = normalize_trace_path(trace_path)
        benchmark = extract_benchmark_name(trace_path)
        trace_file = Path(trace_path).name if trace_path else "unknown"

        record = {
            "Experiment": exp_name,
            "Mix_ID": mix_id,
            "Perm_ID": perm_id,
            "Run_Name": run_name,
            "Core": core_id,
            "Benchmark": benchmark,
            "Trace": trace_file,
        }

        stat_src = core_stats.get(core_id, {})
        for alias, real_name in stats_items:
            record[alias] = stat_src.get(real_name, 0.0)
        records.append(record)

    return records


def load_config(config_path: Path) -> dict:
    if yaml is None:
        raise ModuleNotFoundError(
            "PyYAML is required for this script. Install it with: pip install pyyaml"
        )
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_tasks(config: dict) -> List[Tuple]:
    experiments = config.get("experiments", {})
    if not experiments:
        raise ValueError("YAML 'experiments' is empty.")

    manifest_path = Path(config["manifest_path"]).expanduser()
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    stats_map: Dict[str, str] = config.get("stats", {})
    if not stats_map:
        raise ValueError("YAML 'stats' mapping is empty.")

    num_cores = int(config.get("num_cores", 4))
    core_ids = list(config.get("core_ids", list(range(num_cores))))
    core_cols = [f"core{c}" for c in core_ids]

    needed_cols = {"run_name", "mix_id", "perm_id", *core_cols}
    manifest = pd.read_csv(manifest_path)
    missing_cols = [c for c in needed_cols if c not in manifest.columns]
    if missing_cols:
        raise ValueError(f"Manifest missing columns: {missing_cols}")

    stats_items = list(stats_map.items())
    needed_real_stats = sorted(set(stats_map.values()))

    tasks: List[Tuple] = []
    for exp_name, exp_info in experiments.items():
        root_dir = Path(exp_info["root_dir"]).expanduser()
        for row in manifest.itertuples(index=False):
            row_d = row._asdict()
            run_name = str(row_d["run_name"])
            mix_id = row_d["mix_id"]
            perm_id = row_d["perm_id"]
            core_trace_pairs = [(c, row_d.get(f"core{c}", "")) for c in core_ids]
            tasks.append(
                (
                    exp_name,
                    str(root_dir),
                    run_name,
                    mix_id,
                    perm_id,
                    core_trace_pairs,
                    stats_items,
                    core_ids,
                    needed_real_stats,
                )
            )

    return tasks


def flatten(list_of_lists: Iterable[List[dict]]) -> List[dict]:
    out: List[dict] = []
    for chunk in list_of_lists:
        out.extend(chunk)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fast Scarab multicore stats parser")
    parser.add_argument("--config", default="config_multicore.yaml", help="Path to YAML config")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel workers (default: config 'workers' or CPU count). Use 1 for serial.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=8,
        help="ProcessPool map chunksize (default: 8).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if pd is None:
        raise ModuleNotFoundError(
            "pandas is required for this script. Install it with: pip install pandas"
        )
    if yaml is None:
        raise ModuleNotFoundError(
            "PyYAML is required for this script. Install it with: pip install pyyaml"
        )

    config_path = Path(args.config).expanduser()
    config = load_config(config_path)

    tasks = build_tasks(config)
    total_tasks = len(tasks)
    if total_tasks == 0:
        print("No tasks found.")
        return

    default_workers = int(config.get("workers", os.cpu_count() or 1))
    workers = args.workers if args.workers is not None else default_workers
    workers = max(1, workers)

    print(f"Tasks: {total_tasks} | workers: {workers}")

    parsed_chunks: List[List[dict]] = []
    if workers == 1:
        for t in tasks:
            parsed_chunks.append(parse_one_task(t))
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for chunk in ex.map(parse_one_task, tasks, chunksize=max(1, args.chunksize)):
                parsed_chunks.append(chunk)

    records = flatten(parsed_chunks)
    if not records:
        print("No data found.")
        return

    df = pd.DataFrame(records)

    metrics = config.get("metrics", {})
    if metrics:
        print("Calculating metrics...")
        for metric_name, formula in metrics.items():
            try:
                df[metric_name] = df.eval(formula)
            except Exception as exc:
                print(f"Warning: metric '{metric_name}' failed ({exc}); filling 0.0")
                df[metric_name] = 0.0

    output_file = Path(config.get("output_file", "multicore_results.csv")).expanduser()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False)
    print(f"Rows written: {len(df)}")
    print(f"Output CSV: {output_file}")


if __name__ == "__main__":
    main()
