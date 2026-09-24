/* Copyright 2020 HPS/SAFARI Research Groups
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

/***************************************************************************************
 * File         : addr_trans.c
 * Author       : HPS Research Group
 * Date         : 10/28/2012
 * Description  : "Fake" virtual to physical address translation. Uses a hash
 *function, and does not maintain page tables. Used to randomize DRAM bank
 *mappings.
 ***************************************************************************************/

#include "addr_trans.h"

#include <stdio.h>
#include <stdlib.h>

#include "globals/assert.h"
#include "globals/global_vars.h"
#include "globals/utils.h"

#include "debug/debug_macros.h"

#include "memory/memory.param.h"
#include "ramulator.param.h"
#include "sim.h"

#define DEBUG(proc_id, args...) _DEBUG(proc_id, DEBUG_ADDR_TRANS, ##args)

DEFINE_ENUM(Addr_Translation, ADDR_TRANSLATION_LIST);

static uns32 hsieh_hash(const char* data, int len);
extern uns64 memtrace_get_workload_tag(uns proc_id);
extern uns64 memtrace_get_trace_id(uns proc_id);
extern uns64 memtrace_get_process_id(uns proc_id);
extern uns64 memtrace_get_thread_id(uns proc_id);

/**************************************************************************************/
/* addr_translate: translate virtual address to physical address */

Addr addr_translate(Addr virt_addr) {
  if (ADDR_TRANSLATION == ADDR_TRANS_NONE)
    return virt_addr;

  /* We fake the virtual->physical address translation by scrambling the addr
   * bits just above the page offset. However, aliasing during the scrambling
   * can end up mapping two distinct virtual pages to the same physical frame.
   * To avoid this, when we stick in the scrambled bits, we keep around the
   * original bits and shift them into the high redundant address bits. The high
   * address bits are redundant because they are the output of sign extension
   * (i.e., all 0s or all 1s). */
  uns num_page_offset_bits = LOG2(VA_PAGE_SIZE_BYTES);
  Addr page_index = virt_addr >> num_page_offset_bits;
  uns proc_id = get_proc_id_from_cmp_addr(virt_addr);
  Addr hash_page_index = page_index;

  if (ADDR_TRANSLATION_MEMTRACE_USE_WORKLOAD_ID) {
    const uns64 workload_tag = memtrace_get_workload_tag(proc_id);
    if (workload_tag) {
      // Use canonicalized page index plus workload-stable identity so a workload
      // keeps the same DRAM mapping when moved across cores.
      const Addr canonical_page_index = (convert_to_cmp_addr(0, virt_addr) >> num_page_offset_bits);
      hash_page_index = canonical_page_index ^ workload_tag;
    }
  }
  // we already use the 6 highest bits to store the proc_id.
  // NUM_ADDR_NON_SIGN_EXTEND_BITS tells us how many bits we actually need to
  // keep, and the bits that are left are used to store the original bits after
  // scrambling
  uns num_bits_to_scramble = 58 - NUM_ADDR_NON_SIGN_EXTEND_BITS;
  uns32 orig_bits = page_index & N_BIT_MASK(num_bits_to_scramble);
  Addr hash_source;

  if (ADDR_TRANSLATION == ADDR_TRANS_RANDOM || ADDR_TRANSLATION == ADDR_TRANS_FLIP) {
    hash_source = hash_page_index;
  } else if (ADDR_TRANSLATION == ADDR_TRANS_PRESERVE_BLP || ADDR_TRANSLATION == ADDR_TRANS_PRESERVE_STREAM) {
    /* excluding original_bits from hash source will preserve
       bank-level parallelism among requests with the same upper
       bits */
    hash_source = page_index >> num_bits_to_scramble;
  } else {
    FATAL_ERROR(0, "Unknown ADDR_TRANSLATION: %s\n", Addr_Translation_str(ADDR_TRANSLATION));
  }
  uns32 hash;
  if (ADDR_TRANSLATION == ADDR_TRANS_FLIP) {
    hash = hash_source ^ N_BIT_MASK(num_bits_to_scramble);
  } else {
    hash = hsieh_hash((char*)&hash_source, sizeof(Addr));
  }
  uns32 scrambled_bits = (hash & N_BIT_MASK(num_bits_to_scramble));
  if (ADDR_TRANSLATION == ADDR_TRANS_PRESERVE_BLP) {
    scrambled_bits ^= orig_bits;
  } else if (ADDR_TRANSLATION == ADDR_TRANS_PRESERVE_STREAM) {
    scrambled_bits ^= orig_bits;
    Addr top_orig_bit = (page_index >> (num_bits_to_scramble - 1)) & 1;
    CLRBIT(scrambled_bits, num_bits_to_scramble - 1);
    scrambled_bits |= top_orig_bit << (num_bits_to_scramble - 1);
  }

  /* Construct the physical address subject to two constraints:
     1. the address should retain proc_id in the upper bits
     2. no two page indices should map to the same frame number (otherwise such
        collisions artifically reduce the application's working set) */
  Addr page_offset = virt_addr & N_BIT_MASK(num_page_offset_bits);
  Addr masked_virt_addr = check_and_remove_addr_sign_extended_bits(virt_addr, NUM_ADDR_NON_SIGN_EXTEND_BITS, FALSE);
  Addr orig_masked_virt_addr = convert_to_cmp_addr(0, masked_virt_addr);
  Addr orig_masked_page_index = orig_masked_virt_addr >> num_page_offset_bits;
  Addr masked_page_index_with_scrambled_bits =
      (orig_masked_page_index & (~N_BIT_MASK(num_bits_to_scramble))) | scrambled_bits;
  ASSERT(proc_id, 0 == (masked_page_index_with_scrambled_bits & ~N_BIT_MASK(NUM_ADDR_NON_SIGN_EXTEND_BITS)));
  Addr new_phys_addr = ((Addr)orig_bits << NUM_ADDR_NON_SIGN_EXTEND_BITS) |
                       (masked_page_index_with_scrambled_bits << num_page_offset_bits) | page_offset;

  Addr cmp_addr = convert_to_cmp_addr(proc_id, new_phys_addr);
  DEBUG(proc_id, "%llx => %llx\n", virt_addr, cmp_addr);
  return cmp_addr;
}

void addr_translation_log_event(Addr virt_addr, Addr phys_addr, uns proc_id, uns request_type) {
  static FILE* trace_file = NULL;
  static Counter event_id = 0;

  if (!ADDR_TRANSLATION_TRACE_FILE || !ADDR_TRANSLATION_TRACE_FILE[0]) {
    return;
  }

  if (!trace_file) {
    trace_file = fopen(ADDR_TRANSLATION_TRACE_FILE, "w");
    if (!trace_file) {
      FATAL_ERROR(proc_id, "Cannot open address translation trace file '%s'\n", ADDR_TRANSLATION_TRACE_FILE);
    }
    fprintf(trace_file,
            "event_id,phase,roi_id,sim_time,cycle,committed_insts,sim_core,trace_id,pid,tid,request_type,"
            "translation_mode,mapping_source,virtual_address,physical_address,vpn,pfn\n");
  }

  const char* phase = operating_mode == WARMUP_MODE ? "warmup" : (roi_dump_began ? "roi" : "simulation");
  const long long roi_id = roi_dump_began ? (long long)roi_dump_ID : -1LL;
  const Counter committed_insts = inst_count && proc_id < MAX_NUM_PROCS ? inst_count[proc_id] : 0;
  const uns page_offset_bits = LOG2(VA_PAGE_SIZE_BYTES);
  const Addr canonical_va = convert_to_cmp_addr(0, virt_addr);
  const Addr canonical_pa = convert_to_cmp_addr(0, phys_addr);
  const Addr vpn = canonical_va >> page_offset_bits;
  const Addr pfn = canonical_pa >> page_offset_bits;
  const uns64 trace_id = memtrace_get_trace_id(proc_id);
  const uns64 pid = memtrace_get_process_id(proc_id);
  const uns64 tid = memtrace_get_thread_id(proc_id);
  const char* mapping_source = MEMORY_RANDOM_ADDR ? "memory_random_addr" : "addr_translate";

  fprintf(trace_file,
          "%llu,%s,%lld,%llu,%llu,%llu,%u,%016llx,%llu,%llu,%u,%s,%s,0x%016llx,0x%016llx,0x%llx,0x%llx\n",
          (unsigned long long)event_id++, phase, roi_id, (unsigned long long)sim_time,
          (unsigned long long)cycle_count, (unsigned long long)committed_insts, proc_id,
          (unsigned long long)trace_id, (unsigned long long)pid, (unsigned long long)tid, request_type,
          Addr_Translation_str(ADDR_TRANSLATION), mapping_source, (unsigned long long)virt_addr,
          (unsigned long long)phys_addr, (unsigned long long)vpn, (unsigned long long)pfn);
  if (fflush(trace_file) != 0) {
    FATAL_ERROR(proc_id, "Failed writing address translation trace file '%s'\n", ADDR_TRANSLATION_TRACE_FILE);
  }
}

/**************************************************************************************
 * The code below was adapted from
 *http://www.azillionmonkeys.com/qed/hash.html
 **************************************************************************************/

#if !defined(get16bits)
#define get16bits(d) ((((uns32)(((const uns8*)(d))[1])) << 8) + (uns32)(((const uns8*)(d))[0]))
#endif

uns32 hsieh_hash(const char* data, int len) {
  uns32 hash = len, tmp;
  int rem;

  if (len <= 0 || data == NULL)
    return 0;

  rem = len & 3;
  len >>= 2;

  /* Main loop */
  for (; len > 0; len--) {
    hash += get16bits(data);
    tmp = (get16bits(data + 2) << 11) ^ hash;
    hash = (hash << 16) ^ tmp;
    data += 2 * sizeof(uns16);
    hash += hash >> 11;
  }

  /* Handle end cases */
  switch (rem) {
    case 3:
      hash += get16bits(data);
      hash ^= hash << 16;
      hash ^= ((signed char)data[sizeof(uns16)]) << 18;
      hash += hash >> 11;
      break;
    case 2:
      hash += get16bits(data);
      hash ^= hash << 11;
      hash += hash >> 17;
      break;
    case 1:
      hash += (signed char)*data;
      hash ^= hash << 10;
      hash += hash >> 1;
  }

  /* Force "avalanching" of final 127 bits */
  hash ^= hash << 3;
  hash += hash >> 5;
  hash ^= hash << 4;
  hash += hash >> 17;
  hash ^= hash << 25;
  hash += hash >> 6;

  return hash;
}
