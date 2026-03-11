#ifndef __TLB_H__
#define __TLB_H__

#include "globals/global_types.h"

/**************************************************************************************/
/* Types */

typedef struct TLB_Data_struct {
  uns8 proc_id;
} TLB_Data;

/**************************************************************************************/
/* Prototypes */

void init_tlb(uns8 proc_id);
uns  dtlb_lookup(uns8 proc_id, Addr va);
uns  itlb_lookup(uns8 proc_id, Addr va);
void tlb_warmup(uns8 proc_id, Addr va, Flag is_instruction);

/**************************************************************************************/

#endif /* #ifndef __TLB_H__ */
