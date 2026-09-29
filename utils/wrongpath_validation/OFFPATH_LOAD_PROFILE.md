# Finding a wrong-path load PC

Use an existing memtrace input with an opt, dbg, or vgr build:

```sh
mkdir -p OFFPATH_PROFILE_ROB32
./src/scarab --frontend memtrace --num_cores=1 \
  --cbp_trace_r0=/path/to/4190.zip --warmup=0 --inst_limit=1000000 \
  --node_table_size=32 --bp_mech=tage64k \
  --output_dir=OFFPATH_PROFILE_ROB32 \
  --offpath_load_profile_file=OFFPATH_PROFILE_ROB32/loads.csv
```

Repeat with ROB512, changing `node_table_size` and the output paths only.
The output path is used literally, not relative to `output_dir`.
The summary is written on normal simulator shutdown; aborted runs may leave
an empty file. Profiling is disabled unless an output file is specified.

Columns:

- `core`: simulated core, with separate entries for each core.
- `pc`: untagged instruction PC from the saved trace record.
- `offpath_load_count`: number of generated off-path instruction records with loads.
- `load_operand_count`: sum of load operands across those records.
- `distinct_reused_vas`: exact distinct recorded load VAs, pooled across operands.

Counts cover the entire simulation, including any off-path generation outside
ROI dumps; ROI stats resets do not reset this profiler. Stores and dummy NOPs
without loads are not counted. These are generation counts, not execution,
retirement, or cache-access counts. Each frontend generation call is counted;
multiple speculative BP streams, if enabled, are pooled per core/PC.
The profiler does not modify the saved records or address translation.

To show frequent candidate PCs with more than one observed VA:

```sh
awk -F, 'NR>1 && $5>1' OFFPATH_PROFILE_ROB32/loads.csv | sort -t, -k3,3nr | head -20
```

For instructions with multiple load operands, multiple distinct VAs can simply
reflect different operands. A candidate summary alone does not prove a timing
effect. Follow up with per-event VA logs and on-path record updates for the
chosen PC in both configurations. Do not pair speculative episodes solely by
their occurrence index or cycle.

Exact distinct-VA counting keeps sets in host memory; start with a short run.

Standalone aggregation test:

```sh
c++ -std=c++11 -Wall -Wextra -Werror -Isrc \
  utils/wrongpath_validation/test_offpath_load_profile.cc \
  -o /tmp/test_offpath_load_profile
/tmp/test_offpath_load_profile
```
