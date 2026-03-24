# Wrong-Path Surgical Validation (pin_exec_driven)

This kit validates that Scarab models off-path (wrong-path) flow consistently.

## 1) Build the microbenchmark

```bash
cd /path/to/scarab-private
gcc -O2 -fno-if-conversion -fno-tree-vectorize -fno-omit-frame-pointer \
    -fno-inline -Iutils \
    utils/wrongpath_validation/wrongpath_surgical.c \
    -o utils/wrongpath_validation/wrongpath_surgical
```

## 2) Run in execution-driven mode with pipeview enabled

Example:

```bash
python3 ./bin/scarab_launch.py \
  --program "./utils/wrongpath_validation/wrongpath_surgical 64 2000000 500000" \
  --params ./src/PARAMS.golden_cove \
  --scarab_args "--inst_limit=20000000 --pipeview=1 --pipeview_file=pipeview --num_cores=1"
```

Notes:
- Program args are: `train_len roi_iters warm_iters`.
- The benchmark emits 2 ROI dump phases:
  - ROI-0: train taken, periodic flip to not-taken
  - ROI-1: train not-taken, periodic flip to taken

## 3) Check ROI stats quickly

```bash
python3 ./bin/check_wrongpath_stats.py \
  --fetch fetch.stat.0.out.roi.0 fetch.stat.0.out.roi.1 \
  --core  core.stat.0.out.roi.0  core.stat.0.out.roi.1 \
  --inst  inst.stat.0.out.roi.0  inst.stat.0.out.roi.1 \
  --bp    bp.stat.0.out.roi.0    bp.stat.0.out.roi.1
```

Expected high-level behavior:
- `CBR_RECOVER_MISPREDICT` > 0 in both ROI windows.
- Off-path counters > 0:
  - `FETCH_OFF_PATH`, `FETCHED_OPS_OFF_PATH`, `EXEC_OFF_PATH_INST`
  - `ICACHE_STAGE_OFF_PATH`, `DECODE_STAGE_OFF_PATH`, `EXEC_STAGE_OFF_PATH`
  - `ST_INST_OFFPATH`, `ST_OP_OFFPATH`

## 4) Check off-path PC attribution from pipeview

```bash
python3 ./bin/analyze_wrongpath_pipeview.py \
  --pipeview ./pipeview.0.trace \
  --binary ./utils/wrongpath_validation/wrongpath_surgical \
  --top 20
```

This prints:
- total ops vs off-path ops
- top off-path PCs
- top off-path symbols

The off-path top symbols should be concentrated in the target block that corresponds to the expected wrong branch direction for that ROI pattern.

