#include "tlb.h"

#include "globals/assert.h"
#include "globals/global_defs.h"
#include "globals/global_types.h"

#include "libs/cache_lib.h"
#include "memory/memory.param.h"
#include "statistics.h"

/**************************************************************************************/
/* Macros */

#define PAGE_MASK (~(Addr)(VA_PAGE_SIZE_BYTES - 1))
#define SUPERPAGE_SHIFT 21  /* 2MB region — covers PML4+PDPT+PD levels */

/**************************************************************************************/
/* Local Variables */

static Cache dtlb[MAX_NUM_PROCS];
static Cache itlb[MAX_NUM_PROCS];
static Cache l2_tlb[MAX_NUM_PROCS];
static Cache l3_tlb[MAX_NUM_PROCS];
//static Cache pwc[MAX_NUM_PROCS];

/**************************************************************************************/
/* Helper: lookup L2 TLB + PWC on L1 TLB miss, install into all levels */

static uns tlb_l2_lookup_and_fill(uns8 proc_id, Addr page_addr, Cache* l1_tlb,
                                  Flag is_instruction) {
  Addr dummy_line_addr;
  Addr repl_line_addr;

  /* L2 TLB check */
  TLB_Data* data = (TLB_Data*)cache_access(&l2_tlb[proc_id], page_addr,
                                            &dummy_line_addr, TRUE);
  if (data) {
    /* L2 TLB hit — install into L1 */
    STAT_EVENT(proc_id, is_instruction ? L2_TLB_HIT_ON_ITLB_MISS
                                       : L2_TLB_HIT_ON_DTLB_MISS);
    TLB_Data* l1_entry = (TLB_Data*)cache_insert(
        l1_tlb, proc_id, page_addr, &dummy_line_addr, &repl_line_addr);
    l1_entry->proc_id = proc_id;
    return L2_TLB_LATENCY;
  }

  /* L2 TLB miss — check Page Walk Cache */
  STAT_EVENT(proc_id, is_instruction ? L2_TLB_MISS_ON_ITLB_MISS
                                     : L2_TLB_MISS_ON_DTLB_MISS);

  /* L3 TLB check */
  data = (TLB_Data*)cache_access(&l3_tlb[proc_id], page_addr,
                                            &dummy_line_addr, TRUE);

  uns walk_latency;

  if (data) {
    /* L3 TLB hit */
    STAT_EVENT(proc_id, is_instruction ? L3_TLB_HIT_ON_ITLB_MISS
                                       : L3_TLB_HIT_ON_DTLB_MISS);
    walk_latency = L3_TLB_LATENCY;
  } else {
    /* L3 TLB miss */
    STAT_EVENT(proc_id, is_instruction ? L3_TLB_MISS_ON_ITLB_MISS
                                       : L3_TLB_MISS_ON_DTLB_MISS);
    TLB_Data* l3_tlb_entry = (TLB_Data*)cache_insert(
        &l3_tlb[proc_id], proc_id, page_addr, &dummy_line_addr,
        &repl_line_addr);
    l3_tlb_entry->proc_id = proc_id;
    walk_latency = PAGE_WALK_LATENCY;
  }

/** THIS IS A PWC IMPLEMENTATION **/
//  Addr upper_page_addr = page_addr >> SUPERPAGE_SHIFT;
//  uns walk_latency;
//
//  data = (TLB_Data*)cache_access(&pwc[proc_id], upper_page_addr,
//                                  &dummy_line_addr, TRUE);
//  if (data) {
//    /* PWC hit — only the final PT level needs to be walked */
//    STAT_EVENT(proc_id, PWC_HIT);
//    walk_latency = PWC_HIT_LATENCY;
//  } else {
//    /* PWC miss — full 4-level page walk */
//    STAT_EVENT(proc_id, PWC_MISS);
//    TLB_Data* pwc_entry = (TLB_Data*)cache_insert(
//        &pwc[proc_id], proc_id, upper_page_addr, &dummy_line_addr,
//        &repl_line_addr);
//    pwc_entry->proc_id = proc_id;
//    walk_latency = PAGE_WALK_LATENCY;
//  }

  /* Install into L2 TLB and L1 TLB */
  TLB_Data* l2_entry = (TLB_Data*)cache_insert(
      &l2_tlb[proc_id], proc_id, page_addr, &dummy_line_addr, &repl_line_addr);
  l2_entry->proc_id = proc_id;

  TLB_Data* l1_entry = (TLB_Data*)cache_insert(
      l1_tlb, proc_id, page_addr, &dummy_line_addr, &repl_line_addr);
  l1_entry->proc_id = proc_id;

  return walk_latency;
}

/**************************************************************************************/
/* init_tlb */

void init_tlb(uns8 proc_id) {
  if (PERFECT_TLB)
    return;

  /* line_size = 1 because TLBs are entry-addressed, not block-addressed.
   * cache_size = entries * line_size = entries * 1 = entries.
   * data_size = sizeof(TLB_Data) per entry. */

  init_cache(&dtlb[proc_id], "DTLB",
             DTLB_ENTRIES, DTLB_ASSOC, 1,
             sizeof(TLB_Data), REPL_TRUE_LRU);

  init_cache(&itlb[proc_id], "ITLB",
             ITLB_ENTRIES, ITLB_ASSOC, 1,
             sizeof(TLB_Data), REPL_TRUE_LRU);

  init_cache(&l2_tlb[proc_id], "L2_TLB",
             L2_TLB_ENTRIES, L2_TLB_ASSOC, 1,
             sizeof(TLB_Data), REPL_TRUE_LRU);

  init_cache(&l3_tlb[proc_id], "L3_TLB",
             L3_TLB_ENTRIES, L3_TLB_ASSOC, 1,
             sizeof(TLB_Data), REPL_TRUE_LRU);

//  init_cache(&pwc[proc_id], "PWC",
//             PWC_ENTRIES, PWC_ASSOC, 1,
//             sizeof(TLB_Data), REPL_TRUE_LRU);
}

/**************************************************************************************/
/* dtlb_lookup: returns extra latency in cycles (0 on hit) */

uns dtlb_lookup(uns8 proc_id, Addr va) {
  if (PERFECT_TLB)
    return 0;

  Addr page_addr = va & PAGE_MASK;
  Addr dummy_line_addr;

  /* L1 DTLB check */
  TLB_Data* data = (TLB_Data*)cache_access(&dtlb[proc_id], page_addr,
                                            &dummy_line_addr, TRUE);
  if (data) {
    STAT_EVENT(proc_id, DTLB_HIT);
    return 0;
  }

  STAT_EVENT(proc_id, DTLB_MISS);
  return tlb_l2_lookup_and_fill(proc_id, page_addr, &dtlb[proc_id], FALSE);
}

/**************************************************************************************/
/* itlb_lookup: returns extra latency in cycles (0 on hit) */

uns itlb_lookup(uns8 proc_id, Addr va) {
  if (PERFECT_TLB)
    return 0;

  Addr page_addr = va & PAGE_MASK;
  Addr dummy_line_addr;

  /* L1 ITLB check */
  TLB_Data* data = (TLB_Data*)cache_access(&itlb[proc_id], page_addr,
                                            &dummy_line_addr, TRUE);
  if (data) {
    STAT_EVENT(proc_id, ITLB_HIT);
    return 0;
  }

  STAT_EVENT(proc_id, ITLB_MISS);
  tlb_l2_lookup_and_fill(proc_id, page_addr, &itlb[proc_id], TRUE); // FOR NOW SKIP THE LATENCY
  return 0; //Return always 0 FOR ITLB until I figure it out. Not trivial due to decoupled frontend and FDIP. 
}

/**************************************************************************************/
/* tlb_warmup: populate TLB entries during functional warmup */

void tlb_warmup(uns8 proc_id, Addr va, Flag is_instruction) {
  if (PERFECT_TLB)
    return;

  Addr page_addr = va & PAGE_MASK;
  //Addr upper_page_addr = page_addr >> SUPERPAGE_SHIFT;
  Addr dummy_line_addr;
  Addr repl_line_addr;

  /* Warm appropriate L1 TLB */
  Cache* l1_tlb = is_instruction ? &itlb[proc_id] : &dtlb[proc_id];
  if (!cache_access(l1_tlb, page_addr, &dummy_line_addr, TRUE)) {
    TLB_Data* e = (TLB_Data*)cache_insert(l1_tlb, proc_id, page_addr,
                                           &dummy_line_addr, &repl_line_addr);
    e->proc_id = proc_id;
  }

  /* Warm L2 TLB */
  if (!cache_access(&l2_tlb[proc_id], page_addr, &dummy_line_addr, TRUE)) {
    TLB_Data* e = (TLB_Data*)cache_insert(&l2_tlb[proc_id], proc_id,
                                           page_addr, &dummy_line_addr,
                                           &repl_line_addr);
    e->proc_id = proc_id;
  }

  /* Warm PWC */
  if (!cache_access(&l3_tlb[proc_id], page_addr, &dummy_line_addr, TRUE)) {
    TLB_Data* e = (TLB_Data*)cache_insert(&l3_tlb[proc_id], proc_id,
                                           page_addr, &dummy_line_addr,
                                           &repl_line_addr);
    e->proc_id = proc_id;
  }
}
