/*
 * Surgical wrong-path validation microbenchmark for Scarab pin_exec_driven.
 *
 * Goals:
 * 1) Create controlled branch mispredictions in two complementary phases.
 * 2) Use Scarab ROI dump markers to emit per-phase stats.
 * 3) Keep taken/not-taken target blocks distinct for pipeview PC attribution.
 *
 * Build example:
 *   gcc -O2 -fno-if-conversion -fno-tree-vectorize -fno-omit-frame-pointer \
 *       -fno-inline -Iutils utils/wrongpath_validation/wrongpath_surgical.c \
 *       -o utils/wrongpath_validation/wrongpath_surgical
 */

#include "../scarab_markers.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

volatile uint64_t wp_sink = 0;
volatile uint64_t wp_period = 65;

enum Phase_Mode {
  TRAIN_TAKEN_FLIP_NOT_TAKEN = 0,
  TRAIN_NOT_TAKEN_FLIP_TAKEN = 1,
};

__attribute__((noinline)) static void taken_path_body(uint64_t i) {
  wp_sink += (i * 3u) + 1u;
  __asm__ __volatile__("" ::: "memory");
}

__attribute__((noinline)) static void not_taken_path_body(uint64_t i) {
  wp_sink += (i * 5u) + 7u;
  __asm__ __volatile__("" ::: "memory");
}

static inline int branch_outcome(uint64_t i, enum Phase_Mode mode) {
  uint64_t p = wp_period;
  uint64_t pos = i % p;
  uint64_t flip = p - 1;

  if (mode == TRAIN_TAKEN_FLIP_NOT_TAKEN) {
    /* T T T ... T N pattern */
    return (pos != flip);
  } else {
    /* N N N ... N T pattern */
    return (pos == flip);
  }
}

__attribute__((noinline)) static void run_phase(uint64_t iters, enum Phase_Mode mode) {
  uint64_t i;
  for (i = 0; i < iters; ++i) {
    int cond = branch_outcome(i, mode);
    if (cond) {
      taken_path_body(i);
    } else {
      not_taken_path_body(i);
    }
  }
}

static uint64_t parse_u64_or_default(const char *s, uint64_t dflt) {
  if (!s || !*s) return dflt;
  return (uint64_t)strtoull(s, NULL, 10);
}

int main(int argc, char **argv) {
  uint64_t train_len = (argc > 1) ? parse_u64_or_default(argv[1], 64) : 64;
  uint64_t roi_iters = (argc > 2) ? parse_u64_or_default(argv[2], 2000000) : 2000000;
  uint64_t warm_iters = (argc > 3) ? parse_u64_or_default(argv[3], 500000) : 500000;

  if (train_len < 1) train_len = 1;
  wp_period = train_len + 1;

  printf("wrongpath_surgical: train_len=%llu roi_iters=%llu warm_iters=%llu period=%llu\n",
         (unsigned long long)train_len,
         (unsigned long long)roi_iters,
         (unsigned long long)warm_iters,
         (unsigned long long)wp_period);

  scarab_begin();

  /* Warmup: prime predictor/tables before ROI dumps. */
  run_phase(warm_iters, TRAIN_TAKEN_FLIP_NOT_TAKEN);
  run_phase(warm_iters, TRAIN_NOT_TAKEN_FLIP_TAKEN);

  printf("ROI-1 begin: train-taken flip-not-taken\n");
  scarab_roi_dump_begin();
  run_phase(roi_iters, TRAIN_TAKEN_FLIP_NOT_TAKEN);
  scarab_roi_dump_end();
  printf("ROI-1 end\n");

  printf("ROI-2 begin: train-not-taken flip-taken\n");
  scarab_roi_dump_begin();
  run_phase(roi_iters, TRAIN_NOT_TAKEN_FLIP_TAKEN);
  scarab_roi_dump_end();
  printf("ROI-2 end\n");

  scarab_end();

  /* Keep side effects visible. */
  printf("wrongpath_surgical done. sink=%llu\n", (unsigned long long)wp_sink);
  return 0;
}
