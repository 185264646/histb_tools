import regbin
import unittest

class TestRegReq(unittest.TestCase):
    testcases = [
            # all zero
            (regbin.RegReq(0, 0, 0, True, 0, 0, 0, 0), regbin.RegReq.from_bytes(bytes(3)), 3),
            # PMC_CTRL in sys_clk ( refer to the SDK)
            (regbin.RegReq(0xc8, 1, 1, True, 0, 0, 0, 31), regbin.RegReq.from_bytes(b'\xC8\x20\x1F\x01'), 4),
            # PWM0 in sys_clk
            (regbin.RegReq(0x18, 0x002900DD, 3, True, 100, 1, 0, 31), regbin.RegReq.from_bytes(b'\x18\x60\x3F\x29\x00\xDD\x64'), 7),
            # APLL1 in sys_clk
            (regbin.RegReq(0x4, 0x0800210A, 4, True, 1000, 2, 0, 31), regbin.RegReq.from_bytes(b'\x04\x80\x5F\x08\x00\x21\x0A\x03\xE8'), 9),
    ]

    def test_len(self):
        for i in self.testcases:
            self.assertEqual(len(i[0]), i[2])

    def test_from_bytes(self):
        for i in self.testcases:
            self.assertEqual(i[0], i[1])

class TestRegBlock(unittest.TestCase):
    testcases = [
            (regbin.RegBlock(0xf8a22000, 4, [ regbin.RegReq.from_bytes(b'\xC8\x20\x1F\x01') ]), regbin.RegBlock.from_bytes(b"\xF8\xA2\x20\x00\x04\xC8\x20\x1F\x01"), 9),
    ]

    def test_len(self):
        for i in self.testcases:
            self.assertEqual(len(i[0]), i[2])

    def test_from_bytes(self):
        for i in self.testcases:
            self.assertEqual(i[0], i[1])

class TestRegRegion(unittest.TestCase):
    testcases = [
        (regbin.RegRegion(0x000F, 0x0017, [ regbin.RegBlock.from_bytes(b'\xF8\xA2\x21\x00\x12\x2C\x00\x1F\x30\x00\x1F\x3C\x00\x1F\x40\x00\x1F\x44\x00\x1F\x48\x00\x1F') ]), regbin.RegRegion.from_bytes(b"\x00\x0F\x00\x17\xF8\xA2\x21\x00\x12\x2C\x00\x1F\x30\x00\x1F\x3C\x00\x1F\x40\x00\x1F\x44\x00\x1F\x48\x00\x1F"), 27),
    ]

    def test_len(self):
        for i in self.testcases:
            self.assertEqual(len(i[0]), i[2])

    def test_from_bytes(self):
        for i in self.testcases:
            self.assertEqual(i[0], i[1])

if __name__ == "__main__":
    unittest.main()
