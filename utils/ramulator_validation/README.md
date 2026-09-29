# Wide logical-row regression

This fix preserves `ramulator_use_rest_of_addr_as_row_addr=on`: all address bits
above channel/rank/bank/column and the transaction offset identify the logical
row. It does not impose finite physical capacity or add a page allocator.
Rows above the configured row count are expected under this model, not a sign
that extraction failed. Synthetic VA-to-PA translation is unchanged.

From the repository root, on Linux:

```sh
g++ -std=c++11 -O1 -g -DRAMULATOR -fsanitize=undefined -fno-sanitize-recover=undefined \
  -Isrc/ramulator utils/ramulator_validation/test_wide_address.cc \
  src/ramulator/DDR4.cpp src/ramulator/Config.cpp src/ramulator/StatType.cpp \
  -o /tmp/test_ramulator_wide_address
/tmp/test_ramulator_wide_address
```

On macOS, use `clang++` and add `-Dulong=uint64_t` for the existing Linux-only
`ulong` spelling in the memory-standard sources. The alias is test-build only.

The test invokes `Memory<DDR4>::send`, checks the observed alias pair now has
distinct 40-bit rows, exercises row-hit callbacks and row-table storage, and
checks zero, individual high bits, 10000 random transactions, and narrow rows.
It also drains real controller requests for A/A/B: only the repeated A is a row
hit; the previously aliased B must open its own row.
Assertions must remain enabled.

After building Scarab, repeat the earlier ROB32/ROB512 runs with decoded-PA
tracing. The old undefined-behavior warning should be gone. Run
`bin/check_ramulator_addr_decode.py` on each CSV: distinct transaction addresses
should no longer share decoded tuples in the all-bits-as-row mode. Out-of-range
logical rows can remain. Repeat the mapping/timing comparison; fixed row-hit
classification can change simulated performance, so old IPC is not a golden
reference for the corrected decoder.
