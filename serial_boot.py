#!/usr/bin/python3

import click
import crcmod
import logging
import serial
import serial.threaded
import serial.tools.list_ports
import serial.tools.miniterm
import struct
import sys
import threading
import tqdm
from dataclasses import dataclass
from enum import IntEnum

import image


class Packet(object):
    crc = crcmod.mkCrcFun(0x11021, 0, False)

    def __init__(self, function_code: int, seq: int, payload: bytes):
        self.code = function_code
        self.seq = seq
        self.payload = payload
        self.crc = crcmod.mkCrcFun(0x11021, 0, False)

    def __bytes__(self):
        seq_num = (self.seq + 1) * 255
        ret = self.code.to_bytes(1, "big", signed=False) + seq_num.to_bytes(2, "big", signed=False) + self.payload
        return ret + self.crc(ret).to_bytes(2, "big", signed=False)

    def __str__(self):
        return "Packet: code={}, payload={}".format(self.code, self.payload.hex(sep=' '))

    @classmethod
    def from_bytes(cls, packet: bytes):
        """convert bytes to Packet"""
        # null packet
        if packet == b'':
            return None
        # we need 1 byte code, 2 bytes seq, 2 bytes crc, so 5 is the minimal
        if len(packet) < 5:
            raise ValueError("packet too short")
        if cls.crc(packet):
            raise ValueError("crc not match")
        code = packet[0]
        payload = packet[3:-2]
        return cls(code, 0, payload)


class HisiPacketType(IntEnum):
    """Various enum used as packet type"""
    TypeFrame = 0xBD
    HeadFrame = 0xFE
    DataFrame = 0xDA
    TailFrame = 0xED
    BoardFrame = 0xCE


@dataclass
class HisiTypeFrameResult(object):
    """A class representing the returning struct of SendTypeFrame"""
    CA: bool
    TEE: bool
    multiform: bool
    boot_version: int
    system_id: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'HisiTypeFrameResult':
        """Parse a returned bytes and return Self"""
        assert len(data) == 14 or len(data) == 15 and data.endswith(b'\xAA'), f"Invalid length, got {len(data)}"
        if len(data) == 15:
            data = data[:-1]

        # just ignore checksum, it's already checked
        start_byte, flags, boot_version, system_id = struct.unpack_from('>B2xB2I2x', data)
        assert start_byte == 0xBD, f"type mismatch, got {start_byte}"

        CA = flags & 1
        TEE = flags & 2
        multiform = flags & 4
        return cls(CA, TEE, multiform, boot_version, system_id)


@dataclass
class HisiBoardFrameResult(object):
    """A class representing the returned struct of SendBoardFrame"""
    # There should be some other flags returned, but not documented
    unk_1: int

    @classmethod
    def from_bytes(cls, b: bytes) -> 'HisiBoardFrameResult':
        assert len(b) == 10 or len(b) == 11 and b.endswith(b'\xAA'), f"Invalid length, got {len(b)}"
        if len(b) == 11:
            b = b[:-1]

        start_byte, unk_1 = struct.unpack('>B3xI2x', b)
        assert start_byte == 0xCE, f"type mismatch, got {start_byte}"

        return cls(unk_1)


class HistbSerial(object):
    INTERVAL = .2  # interval between command resending
    MAX_RETRY_TIMES = 10

    def __init__(self, dev=None):
        self.write_stop = threading.Event()
        self.write_stop.set()
        self.write_data = None
        if dev:
            self.dev = dev
        else:
            logging.info('No serial device is given, using default COM port')
            port_list = serial.tools.list_ports.comports()
            if len(port_list) != 1:
                logging.error("zero or multiple com ports found, please specify the COM port")
                raise ValueError('Zero or multiple com ports found')
            # 3 secs is enough, it's good for interrupting the program with Ctrl-C.
            self.dev = serial.Serial(port_list[0].name, 115200, timeout=3)
            logging.debug("using serial device: {}".format(port_list[0].device))

    @staticmethod
    def _crc(data: bytes):
        func = crcmod.mkCrcFun(0x11021, 0, False)
        return func(data)

    def send_frame_result(self, data: bytes, start_byte: bytes, length: int, interval=200, retry_times=10) -> bytes:
        """
        Send a packet periodically and wait for a result frame

        :param data: data send to serial port
        :param start_byte: the start byte of the returning struct
        :param length: the length of the returning struct
        :param interval: resending interval, in msec
        :param retry_times: max retry times
        :returns: the packet(excluding the 0xAA checksum)
        :raises AssertError:
        :raises TimeoutError:
        """
        self.dev.timeout = interval / 1e3
        for i in range(retry_times):
            self.dev.write(data)
            try:
                ret = self.read_packet(start_byte, length, interval)
            except TimeoutError:
                pass
            except Exception as e:
                raise e
            else:
                return ret
        raise TimeoutError("timeout")

    def send_data_ack(self, data: bytes, interval=100, retry_times=10) -> None:
        """
        Send a packet periodically and wait for an ACK

        :param data: data send to serial port
        :param interval: resending interval, in msec
        :param retry_times: max retry times
        :returns: None
        :raises AssertError:
        :raises TimeoutError:
        """
        self.dev.timeout = interval / 1e3
        for i in range(retry_times):
            self.dev.write(data)
            try:
                self.read_ack(interval)
            except TimeoutError:
                pass
            except Exception as e:
                raise e
            else:
                return None
        raise TimeoutError("timeout")

    def read_ack(self, timeout=1000) -> None:
        """
        Read an ACK(0xAA).

        :param timeout: timeout in msecs
        :returns: True - ACK, False - NAK
        :raises TimeoutError:
        """
        ser = self.dev
        ser.timeout = timeout / 1e3

        data = ser.read_until(b'\xAA')

        if not data.endswith(b'\xAA'):
            # broken packet or empty
            sys.stdout.write(data.decode("utf-8"))
            raise TimeoutError("timeout")
        sys.stdout.write(data[:-1].decode("utf-8"))

    def read_packet(self, start_byte: bytes, length: int, timeout=1000) -> bytes:
        """
        Read a packet.

        :param start_byte: the type(first) byte of the return struct
        :param timeout: max timeout in msec
        :param length: the length of the returning struct including the 0xAA checksum status indicator
        :returns: the packet(including the 0xAA checksum)
        :raises AssertError:
        :raises TimeoutError:
        """
        ser = self.dev
        ser.timeout = timeout / 1e3

        data = ser.read_until(b'\xAA')

        msg, delim, payload = data.partition(start_byte)
        # There are 3 situations here:
        # 1. nothing except msg is received, raise Timeout
        # 2. delim found but no 0xAA ending, a partial packet, wait for a little more time to wait for it to finish
        # 3. All good
        if delim == b'':
            # empty
            sys.stdout.write(msg.decode('utf-8'))
            raise TimeoutError('timeout')

        assert delim == start_byte, "start_byte mismatch"

        if not data.endswith(b'\xAA'):
            # partial
            payload += ser.read_until(b'\xAA')
            if not payload.endswith(b'\xAA'):
                raise ValueError('Broken packet')

        sys.stdout.write(msg.decode("utf-8"))
        ret = delim + payload
        assert len(ret) == length, "length mismatch"
        # strip off 0xAA suffix before crc
        assert self._crc(ret[:-1]) == 0, "crc mismatch"

        return ret

    def wait_boot(self):
        """Waiting for the device to power on"""
        # read bootrom message and return
        # BootROM will output "\r\nBootrom start\r\nBoot Media: eMMC\r\n" before starting to wait for incoming instructions
        # But we don't have to wait until all the messages is output, just return as soon as we met \n.
        while True:
            s = self.dev.readline()
            if s != b'':
                break
        click.echo(s)
        logging.info("Device is power on")
        return None

    def send_type_frame(self):
        packet = b'\xBD\x00\xFF\x01\x00\x00\x00\x00\x00\x00\x00\x01\x70\x5E'

        data = self.send_frame_result(packet, b'\xBD', 15)
        result = HisiTypeFrameResult.from_bytes(data)
        return result

    def send_file(self, b: bytes, offset: int):
        # split it into 1KB blocks, append to kb first
        if len(b) % 1024:
            b += bytes(1024 - (len(b) % 1024))
        pkt_lst = [b[i:i + 1024] for i in range(0, len(b), 1024)]
        pkt_index = 0
        pkt_begin = struct.pack(">cii", b'\x01', len(b), offset)

        logging.debug("Sending file at {:#x}, length = {:#x}".format(offset, len(b)))
        # send first packet
        logging.debug("Phase 1 of 3")
        self.send_data_ack(bytes(Packet(0xFE, pkt_index, pkt_begin)))

        # send file
        logging.debug("Phase 2 of 3")
        for i in tqdm.tqdm(pkt_lst):
            pkt_index = (pkt_index + 1) % 256
            self.send_data_ack(bytes(Packet(0xDA, pkt_index, i)))

        # end of transfer
        logging.debug("Phase 3 of 3")
        pkt_index = (pkt_index + 1) % 256
        self.send_data_ack(bytes(Packet(0xED, pkt_index, b'')))

        return None

    def send_board_frame(self):
        """send board frame"""
        payload = b'\xCE\x00\xFF\x01\x12\x34\x56\x78\x12\x34\x56\x78\x9D\xFB'
        self.send_frame_result(payload, b'\xCE', 11)
        return None


def module_print(s: str):
    print("serial_boot: " + s)


@click.command()
@click.argument("fastboot_image", required=True, type=click.File("rb"))
@click.option("--debug", "-d", "debug", type=bool, required=False, default=False, is_flag=True,
              help="Enable debug mode")
@click.option("--terminal", "-t", "terminal", type=bool, required=False, default=False, is_flag=True,
              help="Open a terminal when completed")
def cli(fastboot_image, debug, terminal):
    if debug:
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
    # parse boot image
    bootimg = image.FastbootImageV1(fastboot_image)
    bootimg.parse_image()
    bootimg.extract_images()
    logging.info(bootimg)

    dev = HistbSerial()
    dev.wait_boot()
    module_print("Device is power on")
    module_print("Phase 1: send type frame")
    type_frame = dev.send_type_frame()
    module_print("Phase 1: board info: {}".format(type_frame))
    logging.info("board info: {}".format(type_frame))
    module_print("Phase 2: send head area")
    dev.send_file(bootimg.headarea, 0)
    module_print("Phase 3: send aux area")
    dev.send_file(bootimg.auxcode, bootimg.auxcode_addr)
    module_print("Phase 4: send board frame")
    dev.send_board_frame()
    module_print("Phase 5: resend param area")
    dev.send_file(bootimg.bootreg_def, bootimg.bootregs_addr)
    module_print("Phase 6: send fastboot image")
    dev.send_file(bootimg.image, 0)
    if terminal:
        module_print("Use Ctrl+] to exit, Ctrl+H Ctrl+T shows help")
        term = serial.tools.miniterm.Miniterm(dev.dev, eol="lf")
        term.set_tx_encoding("utf-8")
        term.set_rx_encoding("utf-8")
        b = dev.dev.read_all()
        if b:
            sys.stdout.write(b.decode("utf-8"))
        term.start()
        term.join()
    return None


if __name__ == "__main__":
    cli()
