#!/usr/bin/python3

"""regbin parse tool"""

import logging
import pprint
import struct
from dataclasses import dataclass, asdict
from optparse import OptionParser

@dataclass
class RegReq(object):
    """ A register writting/reading request.

A register request is write/read to a certain memory address. It is capable of
specify a start_bit and a bits_len, that is, you can write an arbitrary value
to a sequence of bits in a DWORD and leave other parts untouched.
Can be seen as one row in the xlsm.
"""
    offset: int
    value: int
    value_len: int
    # False for r, True for w
    rw: bool
    delay: int
    # in bytes (0-3)
    delay_len: int
    # 31 at maximum
    start_bit: int
    # minus 1 (31 at maximum)
    # That is, the actual bits length is the value here plus 1, because writting 0 bit obviously makes no sense
    write_bits_cnt: int

    def __len__(self):
        return 3 + self.value_len + self.delay_len

    @classmethod
    def from_bytes(cls, s: bytes, warn_trailing_garbage = False):
        base_part, dyn_part = s[0:3], s[3:]
        # constant part
        base = struct.unpack(">3B", base_part)
        offset = base[0]
        start_bit = base[1] & 0b11111
        value_len = (base[1] >> 5) & 0b111
        write_bits_cnt = base[2] & 0b11111
        delay_len = (base[2] >> 5) & 0b111
        
        # dynamic part
        # remove trailing garbage
        dyn_part = dyn_part[0:value_len + delay_len]
        value, delay = struct.unpack_from(f"{value_len}s{delay_len}s", dyn_part, 0)
        value = int.from_bytes(value, "big", signed=False)
        delay = int.from_bytes(delay, "big", signed=False)

        if (len(s) != 3 + value_len + delay_len):
            if (warn_trailing_garbage):
                logging.warn("Expected size { 3 + value_len + delay_len }, actual size { len(s) }.")
            else:
                logging.debug("Expected size { 3 + value_len + delay_len }, actual size { len(s) }.")

        return cls(offset, value, value_len, True, delay, delay_len, start_bit, write_bits_cnt)

@dataclass
class RegBlock(object):
    """ A collection of RegReqs.

It defines the base address of a collection of RegReqs and store them in a single block.
Can be seen as multiple lines in the xlsm.
padding: DWORD
"""
    addr_base: int
    # in bytes
    payload_len: int
    reg_req_lst: list[RegReq]

    def __len__(self):
        return self.payload_len + 5

    @classmethod
    def from_bytes(cls, s: bytes, warn_trailing_garbage = False):
        base_part, dyn_part = s[0:5], s[5:]
        # constant part
        base = struct.unpack(">IB", base_part)
        addr_base = base[0]
        payload_len = base[1]

        # dynamic part
        # remove trailing garbage
        dyn_part = dyn_part[0:payload_len]

        cur_pos = 0
        reg_req_lst = []
        while cur_pos < payload_len:
            i = RegReq.from_bytes(dyn_part[cur_pos:], warn_trailing_garbage = False)
            reg_req_lst.append(i)
            cur_pos += len(i)

        if len(s) != 5 + payload_len:
            if (warn_trailing_garbage):
                logging.warn("Expected size { 5 + payload_len }, actual size { len(s) }.")
            else:
                logging.debug("Expected size { 5 + payload_len }, actual size { len(s) }.")

        return cls(addr_base, payload_len, reg_req_lst)

@dataclass
class RegRegion(object):
    """ A collection of RegBlocks

Can be seen as a page in the xlsm
"""

    # short
    # 0x0f or 0x0e ?
    _unk_field: int
    # in bytes
    payload_len: int
    reg_blk_lst: list[RegBlock]

    def __len__(self):
        return 4 + self.payload_len

    @classmethod
    def from_bytes(cls, s: bytes, warn_trailing_garbage = False):
        base_part, dyn_part = s[0:4], s[4:]
        # constant part
        base = struct.unpack(">HH", base_part)
        _unk_field = base[0]
        payload_len = base[1]

        # dynamic part
        # remove trailing garbage
        dyn_part = dyn_part[0:payload_len]

        cur_pos = 0
        reg_blk_lst = []
        while cur_pos < payload_len:
            i = RegBlock.from_bytes(dyn_part[cur_pos:], warn_trailing_garbage = False)
            reg_blk_lst.append(i)
            cur_pos += len(i)

        if len(s) != 4 + payload_len:
            if (warn_trailing_garbage):
                logging.warn("Expected size { 4 + payload_len }, actual size { len(s) }.")
            else:
                logging.debug("Expected size { 4 + payload_len }, actual size { len(s) }.")

        return cls(_unk_field, payload_len, reg_blk_lst)

@dataclass
class RegBin(object):
    """ The Regbin file itself

Can be seen as the xlsm or the regbin file
"""

    # all NUL terminated
    version: str
    build_time: str
    board_type: str

    reg_region_lst: list[RegRegion]

    @classmethod
    def from_bytes(cls, s: bytes, warn_trailing_garbage = False):
        version, __unused, s = s.partition(b'\x00')
        build_time, __unused, s = s.partition(b'\x00')
        board_type, __unused, s = s.partition(b'\x00')

        # There's another padding NUL byte
        s=s[1:]

        cur_pos = 0
        reg_region_lst = []

        # we think the unk_field can not be 0, or we met the end
        while s[cur_pos+1]:
            i = RegRegion.from_bytes(s[cur_pos:], warn_trailing_garbage = False)
            reg_region_lst.append(i)
            cur_pos += len(i)

        return cls(version, build_time, board_type, reg_region_lst)

class MyPrettyPrinter(pprint.PrettyPrinter):
    def format(self, object, context, maxlevels, level):
        if isinstance(object, int):
            return hex(object), True, False
        else:
            return super().format(object, context, maxlevels, level)

if __name__ == "__main__":
    usage = "Usage: %prog [options] filename"
    parser = OptionParser(usage = usage)
    options, args = parser.parse_args()
    if len(args) != 1:
        parser.print_usage()
        exit(1)
    with open(args[0], "r+b") as file:
        s = file.read()
        regbin = RegBin.from_bytes(s, warn_trailing_garbage=False)
        MyPrettyPrinter().pprint(regbin)


