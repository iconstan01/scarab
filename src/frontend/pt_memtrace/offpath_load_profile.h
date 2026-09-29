#ifndef OFFPATH_LOAD_PROFILE_H
#define OFFPATH_LOAD_PROFILE_H

#include <cstdint>
#include <iomanip>
#include <map>
#include <ostream>
#include <set>
#include <utility>

// Counts reconstructed instructions, not executed uops or cache requests.
class OffpathLoadProfile {
  struct Entry {
    uint64_t instances = 0;
    uint64_t operands = 0;
    std::set<uint64_t> addresses;
  };
  std::map<std::pair<unsigned, uint64_t>, Entry> entries;

 public:
  void clear() { entries.clear(); }

  void observe(unsigned core, uint64_t pc, const uint64_t* addresses, unsigned count) {
    if (!count)
      return;
    Entry& entry = entries[std::make_pair(core, pc)];
    ++entry.instances;
    entry.operands += count;
    entry.addresses.insert(addresses, addresses + count);
  }

  void write(std::ostream& out) const {
    out << "core,pc,offpath_load_count,load_operand_count,distinct_reused_vas\n";
    for (const auto& item : entries) {
      out << std::dec << item.first.first << ",0x" << std::hex << item.first.second
          << std::dec << ',' << item.second.instances << ',' << item.second.operands
          << ',' << item.second.addresses.size() << '\n';
    }
  }
};

#endif
