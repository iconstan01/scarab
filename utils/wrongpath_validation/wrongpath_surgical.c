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

#define WP_MEM_WORDS 4096u
#define WP_MEM_MASK (WP_MEM_WORDS - 1u)

volatile uint64_t wp_load_region[WP_MEM_WORDS];
volatile uint64_t wp_store_region[WP_MEM_WORDS];

enum Phase_Mode {
  TRAIN_TAKEN_FLIP_NOT_TAKEN = 0,
  TRAIN_NOT_TAKEN_FLIP_TAKEN = 1,
  TRAIN_PSEUDORAND50 = 2,
};

enum Body_Mode {
  BODY_ALU = 0,
  BODY_MEM_SPLIT = 1,
};

enum Path_Map_Mode {
  PATH_MAP_DEFAULT = 0,
  PATH_MAP_SWAP = 1,
};

__attribute__((noinline)) static void taken_path_body_alu(uint64_t i) {
  wp_sink += (i * 3u) + 1u;
  __asm__ __volatile__("" ::: "memory");
}

__attribute__((noinline)) static void not_taken_path_body_alu(uint64_t i) {
  wp_sink += (i * 5u) + 7u;
  __asm__ __volatile__("" ::: "memory");
}

/* Load-heavy body: used to create a clear off-path load signature. */
__attribute__((noinline)) static void taken_path_body_memsplit(uint64_t i) {
  uint64_t idx0 = (i * 1315423911u) & WP_MEM_MASK;
  uint64_t idx1 = (idx0 + 97u) & WP_MEM_MASK;
  uint64_t a = wp_load_region[idx0];
  uint64_t b = wp_load_region[idx1];
  wp_sink += (a ^ (b + i));
  __asm__ __volatile__("" ::: "memory");
}

/* Store-heavy body: used to create a clear off-path store signature. */
__attribute__((noinline)) static void not_taken_path_body_memsplit(uint64_t i) {
  uint64_t idx0 = (i * 11400714819323198485ull) & WP_MEM_MASK;
  uint64_t idx1 = (idx0 + 53u) & WP_MEM_MASK;
  wp_store_region[idx0] = i ^ 0xD1B54A32D192ED03ULL;
  wp_store_region[idx1] = i + 0x9E3779B97F4A7C15ULL;
  __asm__ __volatile__("" ::: "memory");
}

static void init_mem_regions(void) {
  uint64_t i;
  for (i = 0; i < WP_MEM_WORDS; ++i) {
    wp_load_region[i] = (i * 2654435761u) ^ 0x9E3779B97F4A7C15ULL;
    wp_store_region[i] = i ^ 0xBF58476D1CE4E5B9ULL;
  }
}

static inline int branch_outcome(uint64_t i, enum Phase_Mode mode) {
  static uint64_t prng_state = 0x9e3779b97f4a7c15ULL;
  uint64_t p = wp_period;
  uint64_t pos = i % p;
  uint64_t flip = p - 1;

  if (mode == TRAIN_TAKEN_FLIP_NOT_TAKEN) {
    /* T T T ... T N pattern */
    return (pos != flip);
  } else if (mode == TRAIN_NOT_TAKEN_FLIP_TAKEN) {
    /* N N N ... N T pattern */
    return (pos == flip);
  } else {
    /* Deterministic pseudo-random 50/50 stream.
     * This is intentionally hard for direction predictors. */
    prng_state ^= prng_state << 13;
    prng_state ^= prng_state >> 7;
    prng_state ^= prng_state << 17;
    return (int)(prng_state & 1ULL);
  }
}

static inline void run_body(uint64_t i, int cond, enum Body_Mode body_mode, enum Path_Map_Mode path_map_mode) {
  int route_taken = cond;
  if (path_map_mode == PATH_MAP_SWAP) {
    route_taken = !route_taken;
  }

  if (route_taken) {
    if (body_mode == BODY_MEM_SPLIT) {
      taken_path_body_memsplit(i);
    } else {
      taken_path_body_alu(i);
    }
  } else {
    if (body_mode == BODY_MEM_SPLIT) {
      not_taken_path_body_memsplit(i);
    } else {
      not_taken_path_body_alu(i);
    }
  }
}

__attribute__((noinline)) static void run_phase(uint64_t iters, enum Phase_Mode mode, enum Body_Mode body_mode,
                                                enum Path_Map_Mode path_map_mode) {
  uint64_t i;
  for (i = 0; i < iters; ++i) {
    int cond = branch_outcome(i, mode);
    run_body(i, cond, body_mode, path_map_mode);
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
  uint64_t branch_mode = (argc > 4) ? parse_u64_or_default(argv[4], 0) : 0;
  uint64_t body_mode = (argc > 5) ? parse_u64_or_default(argv[5], 0) : 0;
  uint64_t path_map_mode = (argc > 6) ? parse_u64_or_default(argv[6], 0) : 0;

  if (train_len < 1) train_len = 1;
  if (branch_mode > 1) branch_mode = 1;
  if (body_mode > 1) body_mode = 1;
  if (path_map_mode > 1) path_map_mode = 1;
  wp_period = train_len + 1;

  printf("wrongpath_surgical: train_len=%llu roi_iters=%llu warm_iters=%llu period=%llu branch_mode=%llu body_mode=%llu path_map_mode=%llu\n",
         (unsigned long long)train_len,
         (unsigned long long)roi_iters,
         (unsigned long long)warm_iters,
         (unsigned long long)wp_period,
         (unsigned long long)branch_mode,
         (unsigned long long)body_mode,
         (unsigned long long)path_map_mode);

  init_mem_regions();

  scarab_begin();

  if (!branch_mode) {
    /* Warmup: prime predictor/tables before ROI dumps. */
    run_phase(warm_iters, TRAIN_TAKEN_FLIP_NOT_TAKEN, (enum Body_Mode)body_mode, (enum Path_Map_Mode)path_map_mode);
    run_phase(warm_iters, TRAIN_NOT_TAKEN_FLIP_TAKEN, (enum Body_Mode)body_mode, (enum Path_Map_Mode)path_map_mode);

    printf("ROI-1 begin: train-taken flip-not-taken\n");
    scarab_roi_dump_begin();
    run_phase(roi_iters, TRAIN_TAKEN_FLIP_NOT_TAKEN, (enum Body_Mode)body_mode, (enum Path_Map_Mode)path_map_mode);
    scarab_roi_dump_end();
    printf("ROI-1 end\n");

    printf("ROI-2 begin: train-not-taken flip-taken\n");
    scarab_roi_dump_begin();
    run_phase(roi_iters, TRAIN_NOT_TAKEN_FLIP_TAKEN, (enum Body_Mode)body_mode, (enum Path_Map_Mode)path_map_mode);
    scarab_roi_dump_end();
    printf("ROI-2 end\n");
  } else {
    /* Pseudo-random stress mode for off-path validation. */
    run_phase(warm_iters, TRAIN_PSEUDORAND50, (enum Body_Mode)body_mode, (enum Path_Map_Mode)path_map_mode);

    printf("ROI-1 begin: pseudorand50\n");
    scarab_roi_dump_begin();
    run_phase(roi_iters, TRAIN_PSEUDORAND50, (enum Body_Mode)body_mode, (enum Path_Map_Mode)path_map_mode);
    scarab_roi_dump_end();
    printf("ROI-1 end\n");

    printf("ROI-2 begin: pseudorand50\n");
    scarab_roi_dump_begin();
    run_phase(roi_iters, TRAIN_PSEUDORAND50, (enum Body_Mode)body_mode, (enum Path_Map_Mode)path_map_mode);
    scarab_roi_dump_end();
    printf("ROI-2 end\n");
  }

  scarab_end();

  /* Keep side effects visible. */
  printf("wrongpath_surgical done. sink=%llu\n", (unsigned long long)wp_sink);
  return 0;
}
