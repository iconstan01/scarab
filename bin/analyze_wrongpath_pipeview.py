#!/usr/bin/env python3
"""
Analyze Scarab pipeview output for wrong-path validation.

What it does:
1) Parses O3PipeView records.
2) Finds ops tagged with fetch_offpath.
3) Aggregates off-path PCs and (optionally) maps them to symbols from `nm -n`.

Usage:
  python3 bin/analyze_wrongpath_pipeview.py \
      --pipeview /path/to/pipeview.0.trace \
      --binary /path/to/wrongpath_surgical \
      --top 20
"""

from __future__ import annotations

import argparse
import collections
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


HEADER_PREFIX = "O3PipeView:new:"
EVENT_PREFIX = "O3PipeView:"


@dataclass
class SymbolRange:
  start: int
  end: int
  name: str


def parse_args() -> argparse.Namespace:
  p = argparse.ArgumentParser(description="Analyze off-path PCs from Scarab pipeview")
  p.add_argument("--pipeview", required=True, help="Path to pipeview.<core>.trace")
  p.add_argument("--binary", default="", help="Optional ELF for symbol attribution via `nm -n`")
  p.add_argument("--top", type=int, default=20, help="Top-N PCs/symbols to print")
  return p.parse_args()


def parse_pipeview(path: Path) -> Tuple[int, int, collections.Counter]:
  total_ops = 0
  offpath_ops = 0
  offpath_pc_counts: collections.Counter = collections.Counter()

  current_pc: Optional[int] = None
  current_offpath = False

  with path.open("r", encoding="utf-8", errors="ignore") as f:
    for raw in f:
      line = raw.strip()
      if not line:
        continue

      if line.startswith(HEADER_PREFIX):
        if current_pc is not None:
          total_ops += 1
          if current_offpath:
            offpath_ops += 1
            offpath_pc_counts[current_pc] += 1

        # Format:
        # O3PipeView:new:<fetch_cycle>:<inst_addr_hex>:<uop_addr>:<seq>:<disasm>
        parts = line.split(":")
        if len(parts) < 6:
          current_pc = None
          current_offpath = False
          continue
        try:
          current_pc = int(parts[3], 16)
        except ValueError:
          current_pc = None
        current_offpath = False
        continue

      if line.startswith(EVENT_PREFIX):
        # Format: O3PipeView:<event>:<cycle>
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "fetch_offpath":
          current_offpath = True

  # Flush final op
  if current_pc is not None:
    total_ops += 1
    if current_offpath:
      offpath_ops += 1
      offpath_pc_counts[current_pc] += 1

  return total_ops, offpath_ops, offpath_pc_counts


NM_RE = re.compile(r"^([0-9a-fA-F]+)\s+[tTwW]\s+(.+)$")


def load_symbol_ranges(binary: Path) -> List[SymbolRange]:
  out = subprocess.check_output(["nm", "-n", str(binary)], text=True, stderr=subprocess.STDOUT)
  symbols: List[Tuple[int, str]] = []
  for line in out.splitlines():
    m = NM_RE.match(line.strip())
    if not m:
      continue
    addr = int(m.group(1), 16)
    name = m.group(2)
    symbols.append((addr, name))

  ranges: List[SymbolRange] = []
  for i, (addr, name) in enumerate(symbols):
    end = symbols[i + 1][0] if i + 1 < len(symbols) else (1 << 64) - 1
    ranges.append(SymbolRange(start=addr, end=end, name=name))
  return ranges


def pc_to_symbol(pc: int, ranges: List[SymbolRange]) -> str:
  # linear scan is fine for tiny symbols; no extra deps needed
  for r in ranges:
    if r.start <= pc < r.end:
      return r.name
  return "<unknown>"


def print_report(
    total_ops: int,
    offpath_ops: int,
    offpath_pc_counts: collections.Counter,
    sym_ranges: List[SymbolRange],
    top_n: int,
) -> None:
  pct = (100.0 * offpath_ops / total_ops) if total_ops else 0.0
  print(f"Total ops in pipeview: {total_ops}")
  print(f"Off-path ops:          {offpath_ops} ({pct:.3f}%)")
  print("")

  print(f"Top {top_n} off-path PCs:")
  for pc, cnt in offpath_pc_counts.most_common(top_n):
    sym = pc_to_symbol(pc, sym_ranges) if sym_ranges else ""
    if sym:
      print(f"  0x{pc:x}  count={cnt:<8d} symbol={sym}")
    else:
      print(f"  0x{pc:x}  count={cnt}")

  if sym_ranges:
    sym_counts: Dict[str, int] = collections.Counter()
    for pc, cnt in offpath_pc_counts.items():
      sym_counts[pc_to_symbol(pc, sym_ranges)] += cnt
    print("")
    print(f"Top {top_n} off-path symbols:")
    for name, cnt in collections.Counter(sym_counts).most_common(top_n):
      print(f"  {name:<40s} {cnt}")


def main() -> None:
  args = parse_args()
  pipeview = Path(args.pipeview).expanduser()
  if not pipeview.exists():
    raise FileNotFoundError(f"Pipeview file not found: {pipeview}")

  sym_ranges: List[SymbolRange] = []
  if args.binary:
    binary = Path(args.binary).expanduser()
    if not binary.exists():
      raise FileNotFoundError(f"Binary not found: {binary}")
    sym_ranges = load_symbol_ranges(binary)

  total_ops, offpath_ops, offpath_pc_counts = parse_pipeview(pipeview)
  print_report(total_ops, offpath_ops, offpath_pc_counts, sym_ranges, args.top)


if __name__ == "__main__":
  main()

