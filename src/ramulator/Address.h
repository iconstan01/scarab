#ifndef RAMULATOR_ADDRESS_H
#define RAMULATOR_ADDRESS_H

#include <cassert>
#include <cstdint>

namespace ramulator {

// Signed to retain the -1 wildcard used by refresh and precharge requests.
// Rows fit after removing at least the transaction-offset bit from a 64-bit PA.
using AddressField = int64_t;

inline uint64_t slice_address_bits(uint64_t& address, unsigned bits) {
    assert(bits <= 64);
    if (bits == 64) {
        const uint64_t result = address;
        address = 0;
        return result;
    }
    const uint64_t result = address & ((uint64_t(1) << bits) - 1);
    address >>= bits;
    return result;
}

inline unsigned address_bit_width(uint64_t address) {
    unsigned bits = 0;
    while (address) {
        ++bits;
        address >>= 1;
    }
    return bits;
}

} // namespace ramulator

#endif
