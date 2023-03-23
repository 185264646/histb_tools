#!/usr/bin/python
# -*- coding:utf-8 -*-
import logging
import os

class Fastboot_image(object):
    def __init__(self, file):
        self.image=None
        self.auxcode_addr=0
        self.auxcode_size=0
        self.auxcode=None
        self.bootreg_size=0
        self.bootreg_def=None
        self.bootreg_def_addr=0
        self.bootregs_addr=0
        self.bootregs=[]
        self.headarea_size=0
        self.headarea=None
        self.auxarea_size=0
        self.extracted=False
        self.image = file.read()
        length = len(self.image)
        if length > 0x200000 or length < 0xF000:
            # reject image larger than 2M or smaller than 56K
            raise ValueError("Image too big or too small")
        return None

    def __str__(self):
        ret = []
        ret.append("auxcode address: {:#010X}".format(self.auxcode_addr))
        ret.append("auxcode size: {:#010X}".format(self.auxcode_size))
        ret.append("bootreg size: {:#010X}".format(self.bootreg_size))
        ret.append("default bootreg address: {:#010X}".format(self.bootreg_def_addr))
        ret.append("bootregs address: {:#010X}".format(self.bootregs_addr))
        ret.append("bootregs count: {}".format(len(self.bootregs)))
        return "\n".join(ret)

    def parse_image(self):
        """Fill in the fields in class"""
        # Fill in auxcode fields
        self.auxcode_addr = int.from_bytes(self.image[0x214:0x218], "little")
        self.auxcode_size = int.from_bytes(self.image[0x218:0x21C], "little")

        # Fill in bootreg default fields
        self.bootreg_size = int.from_bytes(self.image[0x2FE8:0x2FEC], "little")
        self.bootreg_def_addr = 0x480 # Fixed to 0x480

        # Fill in bootregs address
        self.bootregs_addr =int.from_bytes(self.image[0x2FE4:0x2FE8], "little")
        return None

    def extract_images(self):
        self.headarea = self.image[0:self.auxcode_addr]
        auxcode_end = self.auxcode_addr + self.auxcode_size
        self.auxcode = self.image[self.auxcode_addr:auxcode_end]

        bootreg_def_end = self.bootreg_def_addr + self.bootreg_size
        self.bootreg_def = self.image[self.bootreg_def_addr:bootreg_def_end]

        # begin to extract bootregs
        for i in range(8): # No more than 8 bootregs
            begin_addr = self.bootregs_addr + i * self.bootreg_size
            end_addr = self.bootregs_addr + (i + 1) * self.bootreg_size
            temp = self.image[begin_addr:end_addr]
            if temp[0] == 0:
                # if the first byte is 0, we think reglist is over
                break
            self.bootregs.append(temp)

        if len(self.bootregs) and (self.bootregs[0] != self.bootreg_def):
            # default bootreg is not identical to the first item in bootreg_list
            # output a warning
            logging.warn("bootreg in Param Area is not identical to the first item in bootreg_list, image might have corrupted")
        self.extracted = True
        return None

    def truncate_to_minimal(self):
        if not self.extracted:
            return None
        self.auxcode = self.auxcode.rstrip(b'\x00')
        self.bootreg_def = self.bootreg_def.rstrip(b'\x00')
        self.bootregs = [ i.rstrip(b'\x00') for i in self.bootregs ]
        return None

    def write_to_directory(self, path: str):
        """Extract images to a directory"""
        if not self.extracted:
            return None
        os.makedirs(path, exist_ok=True)
        os.chdir(path)
        # We extract 2 kinds of images: AUXCODE.bin and BOOT_x.reg
        with open("AUXCODE.img", "wb") as f:
            f.write(self.auxcode)

        # if bootregs is empty, we use bootreg_def, otherwise use bootreg_list directly
        if len(self.bootregs) == 0:
            with open("BOOT_0.reg", "wb") as f:
                f.write(self.bootreg_def)
        else:
            index = 0
            for i in self.bootregs:
                with open("BOOT_{}.reg".format(index), "wb") as f:
                    f.write(i)
                index += 1
        return None
