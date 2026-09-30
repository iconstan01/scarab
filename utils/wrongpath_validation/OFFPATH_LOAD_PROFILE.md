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

## Detailed history for a selected PC

Add these arguments to the same run command (the PC accepts hexadecimal):

```sh
--offpath_load_trace_pc=0x7fffef498728 \
--offpath_load_trace_file=OFFPATH_PROFILE_ROB32/selected_load.csv
```

Use a separate output path for ROB512, keeping the trace and instruction limit
identical. This logger also works in opt builds and does not require the summary
profiler to be enabled. It covers all cores for the selected untagged PC.

The CSV records `event_id,event,core,cycle,sim_time,committed_insts,pc,`
`onpath_observation,map_version,load_operand,old_va,va`.

- `map_insert`: first saved record for this PC.
- `map_update`: on-path read replaces the saved record, for any replacement reason.
- `onpath_observe`: on-path read leaves the saved record unchanged.
- `offpath_generate`: wrong-path generation copies the saved VA; `old_va` is empty.

Each event has one row per load operand. A removed operand has an empty `va`;
an added operand has an empty `old_va`. `onpath_observation` counts on-path reads
of this PC per core; `map_version` increments on inserts/replacements. Together
these identify the cached context used by an off-path generation. They do not
identify the originating mispredicted branch or guarantee that two speculative
episodes in different runs correspond. Identical versions can have different
numbers of off-path generations across runs. Different cycles alone are not
different addresses. On-path updates occur at trace read, not retirement.

The logger does not track execution or cache access. Events span warmup and ROI
resets; committed counts may reset, so use `event_id` for file order. Output is
buffered and completed at normal shutdown; aborts may lose trailing rows.

Compare two selected-PC event logs:

```sh
python3 bin/compare_offpath_load_traces.py \
  --baseline ANALYSE_MAPPINGS_WRONG_PATH/ROB32_NAV_4190/selected_load.csv \
  --candidate ANALYSE_MAPPINGS_WRONG_PATH/ROB512_NAV_4190/selected_load.csv \
  --output-prefix ANALYSE_MAPPINGS_WRONG_PATH/ROB32_vs_ROB512_selected_load
```

The output reports the union/intersection of reused VA keys, counts, and the
number of matching on-path observation/map-version contexts with different VAs.
It writes per-VA, off-path-context, and on-path-context CSVs. Different VAs in a matched
context show changed reconstruction for the selected PC; one-run-only contexts
or changed counts can instead reflect different wrong-path generation. The
context is not a unique branch-misprediction ID. Interpret one-run-only VAs
alongside the on-path context history rather than pairing events by row number.

Standalone aggregation test:

```sh
c++ -std=c++11 -Wall -Wextra -Werror -Isrc \
  utils/wrongpath_validation/test_offpath_load_profile.cc \
  -o /tmp/test_offpath_load_profile
/tmp/test_offpath_load_profile
```
