#!/usr/bin/env python3
"""
Extract key wrong-path counters from Scarab stat files.

Usage:
  python3 bin/check_wrongpath_stats.py \
      --fetch fetch.stat.0.out.roi.0 fetch.stat.0.out.roi.1 \
      --core core.stat.0.out.roi.0 core.stat.0.out.roi.1 \
      --inst inst.stat.0.out.roi.0 inst.stat.0.out.roi.1 \
      --bp bp.stat.0.out.roi.0 bp.stat.0.out.roi.1
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, Iterable, List


STAT_RE = re.compile(r"^\s*([A-Z0-9_]+)\s+([0-9]+)")


FETCH_KEYS = [
    "FETCH_OFF_PATH",
    "FETCHED_OPS_OFF_PATH",
    "EXEC_OFF_PATH_INST",
    "CYCLES_RESTEER_MISPRED",
    "CYCLES_RESTEER_MISFETCH",
]

CORE_KEYS = [
    "ICACHE_STAGE_OFF_PATH",
    "DECODE_STAGE_OFF_PATH",
    "UOPQ_STAGE_OFF_PATH",
    "EXEC_STAGE_OFF_PATH",
    "DFE_GEN_OFF_PATH_FT",
]

INST_KEYS = [
    "ST_INST_OFFPATH",
    "ST_OP_OFFPATH",
    "ST_OP_NOP",
    "ST_MEM_LD_OFFPATH",
    "ST_MEM_ST_OFFPATH",
]

BP_KEYS = [
    "CBR_RECOVER_MISPREDICT",
    "CBR_RECOVER_MISFETCH",
    "BR_RECOVER",
    "CBR_RECOVER_MISPREDICT_OFF_PATH",
    "CBR_RECOVER_MISFETCH_OFF_PATH",
]


def parse_stat_file(path: Path) -> Dict[str, int]:
  d: Dict[str, int] = {}
  with path.open("r", encoding="utf-8", errors="ignore") as f:
    for line in f:
      m = STAT_RE.match(line)
      if not m:
        continue
      d[m.group(1)] = int(m.group(2))
  return d


def print_block(label: str, paths: Iterable[Path], keys: List[str]) -> None:
  paths = list(paths)
  if not paths:
    return
  print(f"\n[{label}]")
  parsed = [(p, parse_stat_file(p)) for p in paths]
  for p, _ in parsed:
    print(f"  file: {p}")
  print("")
  for k in keys:
    vals = [d.get(k, 0) for _, d in parsed]
    vals_s = "  ".join(f"{v:>12d}" for v in vals)
    print(f"{k:<40s} {vals_s}")


def parse_args() -> argparse.Namespace:
  ap = argparse.ArgumentParser(description="Check wrong-path-related Scarab counters")
  ap.add_argument("--fetch", nargs="*", default=[])
  ap.add_argument("--core", nargs="*", default=[])
  ap.add_argument("--inst", nargs="*", default=[])
  ap.add_argument("--bp", nargs="*", default=[])
  return ap.parse_args()


def to_paths(raw: List[str]) -> List[Path]:
  return [Path(x).expanduser() for x in raw]


def main() -> None:
  args = parse_args()
  print_block("fetch", to_paths(args.fetch), FETCH_KEYS)
  print_block("core", to_paths(args.core), CORE_KEYS)
  print_block("inst", to_paths(args.inst), INST_KEYS)
  print_block("bp", to_paths(args.bp), BP_KEYS)


if __name__ == "__main__":
  main()

