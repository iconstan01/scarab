#include "MemoryFactory.h"

#include <cassert>
#include <cstdint>
#include <iostream>
#include <random>
#include <set>
#include <sstream>

using namespace ramulator;

static unsigned activates = 0;
static void record_stat(int, int event) {
    if (event == int(StatCallbackType::DRAM_ACT))
        ++activates;
}

static std::vector<AddressField> expected_decode(uint64_t pa) {
    // Scarab DDR4: 64-byte transaction, 1 channel/rank, 128 transaction
    // columns, 4 bank groups, 4 banks; all remaining bits are the row.
    return {0, 0, AddressField((pa >> 13) & 3), AddressField((pa >> 15) & 3),
            AddressField(pa >> 17), AddressField((pa >> 6) & 127)};
}

static std::vector<AddressField> decode(Memory<DDR4>& memory, uint64_t pa) {
    auto& queue = memory.ctrls[0]->readq.q;
    queue.clear();
    Request request(static_cast<long>(pa), Request::Type::READ, 0);
    assert(memory.send(request));
    assert(queue.size() == 1);
    const auto fields = queue.back().addr_vec;
    assert(fields == expected_decode(pa));
    return fields;
}

int main() {
    static_assert(sizeof(long) == 8, "Ramulator requires a 64-bit long address");
    static_assert(sizeof(AddressField) == 8, "Decoded row must be 64-bit");
    uint64_t bits = UINT64_MAX;
    assert(slice_address_bits(bits, 0) == 0 && bits == UINT64_MAX);
    assert(slice_address_bits(bits, 64) == UINT64_MAX && bits == 0);
    assert(address_bit_width(0) == 0);
    assert(address_bit_width(UINT64_MAX) == 64);

    Config config;
    config.set_core_num(1);
    config.add("org", "DDR4_8Gb_x8");
    config.add("speed", "DDR4_3200");
    config.add("channels", "1");
    config.add("ranks", "1");
    config.add("bank_groups", "4");
    config.add("banks", "4");
    config.add("rows", "65536");
    config.add("columns", "1024");
    config.add("channel_width", "64");
    config.add("use_rest_of_addr_as_row_addr", "on");
    config.add("scheduling_policy", "FRFCFS");
    auto* spec = new DDR4(config);
    auto* memory = MemoryFactory<DDR4>::populate_memory(config, spec, 1, 1, record_stat);
    assert(memory->tx_bits == 6);
    assert(memory->addr_bits[int(DDR4::Level::Column)] == 7);

    decode(*memory, 0);
    decode(*memory, UINT64_MAX);
    decode(*memory, uint64_t(1) << 63);
    for (unsigned bit = 0; bit < 64; ++bit)
        decode(*memory, uint64_t(1) << bit);

    memory->addr_decode_trace = std::tmpfile();
    assert(memory->addr_decode_trace);
    const auto first = decode(*memory, UINT64_C(0x01b27ffff7f72000));
    const auto second = decode(*memory, UINT64_C(0x01b47ffff7f72000));
    const int row = int(DDR4::Level::Row);
    assert(first[row] == INT64_C(0xd93ffffbfb));
    assert(second[row] == INT64_C(0xda3ffffbfb));
    assert(first != second);
    std::rewind(memory->addr_decode_trace);
    for (const auto& expected : {first, second}) {
        char line[1024];
        assert(std::fgets(line, sizeof(line), memory->addr_decode_trace));
        std::istringstream stream(line);
        std::string field;
        for (int column = 0; column <= 5; ++column)
            assert(bool(std::getline(stream, field, ',')));
        assert(std::stoll(field) == expected[row]);
        assert(bool(std::getline(stream, field, ','))); // configured rows
        assert(bool(std::getline(stream, field))); // tuple
        std::ostringstream tuple;
        for (size_t i = 0; i < expected.size(); ++i)
            tuple << (i ? ":" : "") << expected[i];
        assert(field == tuple.str());
    }
    std::fclose(memory->addr_decode_trace);
    memory->addr_decode_trace = nullptr;

    // Exercise the real ACT/RD callbacks, row-state keys and row-table storage.
    auto* bank = memory->ctrls[0]->channel->children[0]->children[first[2]]->children[first[3]];
    spec->lambda[int(DDR4::Level::Bank)][int(DDR4::Command::ACT)](bank, first[row]);
    assert(bank->check_row_hit(DDR4::Command::RD, first.data()));
    assert(!bank->check_row_hit(DDR4::Command::RD, second.data()));
    auto* table = memory->ctrls[0]->rowtable;
    table->update(DDR4::Command::ACT, first, 1);
    table->update(DDR4::Command::RD, first, 2);
    assert(table->get_open_row(first) == first[row]);
    assert(table->get_hits(first) == 1);
    assert(table->get_hits(second) == 0);
    table->update(DDR4::Command::PRE, first, 3);
    assert(table->get_open_row(first) == -1);
    spec->lambda[int(DDR4::Level::Bank)][int(DDR4::Command::PRE)](bank, first[row]);

    std::mt19937_64 random(12345);
    std::set<uint64_t> transactions;
    std::set<std::vector<AddressField>> tuples;
    for (unsigned i = 0; i < 10000; ++i) {
        const uint64_t pa = random();
        transactions.insert(pa >> 6);
        tuples.insert(decode(*memory, pa));
    }
    assert(transactions.size() == tuples.size());

    // Narrow valid rows retain their old, defined decoding. The off mode
    // deliberately discards excess high bits, as before.
    memory->use_rest_of_addr_as_row_addr = false;
    for (uint64_t pa : {UINT64_C(0), UINT64_C(0x1ffffffff)})
        decode(*memory, pa);
    memory->ctrls[0]->readq.q.clear();
    Request bounded(static_cast<long>(UINT64_MAX), Request::Type::READ, 0);
    assert(memory->send(bounded));
    assert(memory->ctrls[0]->readq.q.back().addr_vec[row] == 65535);
    memory->ctrls[0]->readq.q.clear();
    memory->use_rest_of_addr_as_row_addr = true;
    unsigned completed = 0;
    for (uint64_t pa : {UINT64_C(0x01b27ffff7f72000),
                        UINT64_C(0x01b27ffff7f72000),
                        UINT64_C(0x01b47ffff7f72000)}) {
        const unsigned target = completed + 1;
        Request request(static_cast<long>(pa), Request::Type::READ,
                        [&](Request& result) {
                            assert(result.addr_vec == expected_decode(uint64_t(result.addr)));
                            ++completed;
                        }, 0);
        assert(memory->send(request));
        for (unsigned cycle = 0; completed < target && cycle < 1000; ++cycle)
            memory->tick();
        assert(completed == target);
    }
    assert(activates == 2);
    assert(table->get_open_row(second) == second[row]);
    delete memory;
    std::cout << "PASS: wide decode, collision pair, row state, row table, controller scheduling, zero/high-bit addresses, 10000 random transactions\n";
}
