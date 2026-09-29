#include "frontend/pt_memtrace/offpath_load_profile.h"

#include <cassert>
#include <sstream>

int main() {
  OffpathLoadProfile profile;
  const uint64_t first[] = {0x1000};
  const uint64_t second[] = {0x2000, 0x1000};
  profile.observe(0, 0x400100, first, 1);
  profile.observe(0, 0x400100, first, 1);
  profile.observe(0, 0x400100, second, 2);
  profile.observe(1, 0x400100, first, 1);
  profile.observe(0, 0x400200, first, 0);
  std::ostringstream out;
  profile.write(out);
  assert(out.str() ==
         "core,pc,offpath_load_count,load_operand_count,distinct_reused_vas\n"
         "0,0x400100,3,4,2\n"
         "1,0x400100,1,1,1\n");
  profile.clear();
  std::ostringstream empty;
  profile.write(empty);
  assert(empty.str() ==
         "core,pc,offpath_load_count,load_operand_count,distinct_reused_vas\n");
}
