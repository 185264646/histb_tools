import click
import crcmod
import image
import logging
import serial
import serial.threaded
import serial.tools.list_ports
import serial.tools.miniterm
import struct
import sys
import threading
import tqdm
from enum import IntEnum

g_pkt_recv = threading.Event() # indicate a packet is received, should be cleared before new packet arrival
g_ret_data = None # data returned by thread, is set by Packet.process()

class HisiPacketizer(serial.threaded.Packetizer):
    TERMINATOR = b'\xAA' # TODO: handle 0x55('U'), indicating CRC mismatch

    def handle_packet(self, packet):
        logging.debug("packet received: {}".format(packet.hex()))
        # a packet has 3 parts:
        # 1. printable ASCII message(optional): simply output to stdout
        # 2. operation result(optional): start with a non-ASCII byte, can be parsed with Packet.from_bytes()
        # 3. terminator: 0xAA

        # Now we split the packet into 3 parts and do essential checks
        msg, op_result = [], []

        is_reading_msg = True # initial state is to read ASCII message
        for i in packet:
            if is_reading_msg and i < 0x80:
                msg.append(i)
            elif i == 0xAA:
                break
            else:
                op_result.append(i)
                is_reading_msg = False # Now we are reading result

        msg, op_result = bytes(msg), bytes(op_result)

        # First: write msg to stdout
        if msg != b'':
            click.echo(msg.decode("ascii"))

        # Second: parse and process packet
        cls_pkt = Packet.from_bytes(op_result)

        # store packet to global variable, and broadcast an event
        global g_pkt_recv, g_ret_data
        if g_pkt_recv.is_set():
            raise ValueError("A new packet is received with previous packet not processed")
        else:
            g_ret_data = cls_pkt
            g_pkt_recv.set()

        return None


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


class Histb_serial(object):
    INTERVAL = .2 # interval between command resending
    MAX_RETRY_TIMES = 10

    def __init__(self, dev = None):
        self.write_stop = threading.Event()
        self.write_stop.set()
        self.write_data=None
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

    def init_reader_thread(self):
        """Initialize reader thread"""
        self.reader_thr = serial.threaded.ReaderThread(self.dev, HisiPacketizer)
        self.reader_thr.start()
        return None


    def send_frame_result(self, data: bytes, start_byte: bytes, length: int, interval = 100, retry_times = 10) -> bytes:
        """
        Send a packet periodically and wait for an result frame

        :param data: data send to serial port
        :param start_byte: the start byte of the returning struct
        :param length: the length of the returning struct
        :param interval: resending interval, in msec
        :param retry_times: max retry times
        :returns: the packet(excluding the 0xAA checksum)
        :raises AssertError:
        :raises TimeoutError:
        """
        ret = b''
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

    def send_data_ack(self, data: bytes, interval = 100, retry_times = 10) -> None:
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

    def read_ack(self, timeout = 1000) -> None:
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


    def read_packet(self, start_byte: bytes, length: int, timeout = 1000) -> bytes:
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

        if not data.endswith(b'\xAA'):
            # broken packet or empty
            sys.stdout.write(data.decode("utf-8"))
            raise TimeoutError("timeout")

        msg, delim, payload = data.partition(start_byte)
        assert delim == start_byte, "start_byte mismatch"

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

    def get_chip_id(self):
        ser = self.dev
        chip_id_packet = b'\xBD\x00\xFF\x01\x00\x00\x00\x00\x00\x00\x00\x01\x70\x5E'

        global g_pkt_recv, g_ret_data
        g_pkt_recv.clear()

        # write until new packet received, try 5 times at most
        i = 0
        while not g_pkt_recv.is_set() and i < self.MAX_RETRY_TIMES:
            self.reader_thr.write(bytes(chip_id_packet))
            logging.debug("Writing get_chip_id packet: {}".format(chip_id_packet.hex()))
            g_pkt_recv.wait(self.INTERVAL)
            i+=1

        if not g_pkt_recv.is_set():
            logging.fatal("get_chip_id timeout! Check your TX->RX connection.")
            raise ValueError("Timeout")

        # parse struct
        instruction = g_ret_data.code
        logging.info("get_chip_id: got a packet: {}".format(g_ret_data))
        sub_instruction, chip_id = struct.unpack(">c8s", g_ret_data.payload)
        g_pkt_recv.clear()
        assert(instruction == 0xBD)
        assert(sub_instruction == b'\x08')
        return chip_id

    def send_file(self, b: bytes, offset: int):
        # split it into 1KB blocks, append to kb first
        if len(b) % 1024:
            b+=bytes(1024 - (len(b)%1024))
        pkt_lst = [ b[i:i+1024] for i in range(0, len(b), 1024) ]
        pkt_index = 0
        pkt_begin = struct.pack(">cii", b'\x01', len(b), offset)

        logging.debug("Sending file at {:#x}, length = {:#x}".format(offset, len(b)))
        # send first packet
        logging.debug("Phase 1 of 3")
        global g_pkt_recv
        i = 0
        while not g_pkt_recv.is_set() and i < self.MAX_RETRY_TIMES:
            pkt = Packet(0xFE, pkt_index, pkt_begin)
            self.reader_thr.write(bytes(pkt))
            logging.debug("Sending packet: {}".format(pkt))
            g_pkt_recv.wait(self.INTERVAL)
            i+=1
        if not g_pkt_recv.is_set(): # Timeout
            raise ValueError("Timeout")
        g_pkt_recv.clear()

        # send file
        logging.debug("Phase 2 of 3")
        for i in tqdm.tqdm(pkt_lst):
            pkt_index=(pkt_index+1)%256
            self.reader_thr.write(bytes(Packet(0xDA, pkt_index, i)))
            g_pkt_recv.wait(.5) # 0.5 sec should be enough
            if not g_pkt_recv.is_set(): # timeout
                raise ValueError("Timeout")
            g_pkt_recv.clear()

        # end of transfer
        logging.debug("Phase 3 of 3")
        pkt_index=(pkt_index+1)%256
        self.reader_thr.write(bytes(Packet(0xED, pkt_index, b'')))
        g_pkt_recv.wait(.5)
        if not g_pkt_recv.is_set(): # timeout
            raise ValueError("Timeout")
        g_pkt_recv.clear()

        return None

    def decrypt(self):
        """send decrypt request"""
        # The algorithm to calc the key is currently unknown, hardcode it temporarily
        global g_pkt_recv, g_ret_data
        i = 0
        # Hubei HC2910
        # decrypt_payload = b'\x01\x00\x09\xBB\x96\x00\x09\xBB\x96'
        # Henan HC2910
        decrypt_payload = b'\x01\x00\x07\xf8\x2e\x00\x07\xf8\x2e'
        while not g_pkt_recv.is_set() and i < self.MAX_RETRY_TIMES:
            pkt = Packet(0xCE, 0, decrypt_payload)
            self.reader_thr.write(bytes(pkt))
            logging.debug("Sending packet: {}".format(pkt))
            g_pkt_recv.wait(self.INTERVAL)
            i+=1
        if not g_pkt_recv.is_set(): # Timeout
            raise ValueError("Timeout")
        assert(g_ret_data.payload.startswith(b'\x04\x00')) # Decrypt success
        g_pkt_recv.clear()
        return None

def module_print(s: str):
    print("serial_boot: "+s)

@click.command()
@click.argument("fastboot_image", required=True, type=click.File("rb"))
@click.option("--debug", "-d", "debug", type=bool, required=False, default=False, is_flag=True, help="Enable debug mode")
@click.option("--terminal", "-t", "terminal", type=bool, required=False, default=False, is_flag=True, help="Open a terminal when completed")
def cli(fastboot_image, debug, terminal):
    if debug:
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
    # parse boot image
    bootimg = image.Fastboot_image(fastboot_image)
    bootimg.parse_image()
    bootimg.extract_images()
    logging.info(bootimg)

    dev = Histb_serial()
    dev.wait_boot()
    module_print("Device is power on")
    dev.init_reader_thread()
    module_print("Phase 1: get chip id")
    chip_id = dev.get_chip_id()
    module_print("Phase 1: chip id: {}".format(chip_id.hex()))
    logging.info("chip_id is: {}".format(chip_id.hex()))
    module_print("Phase 2: send head area")
    dev.send_file(bootimg.headarea, 0)
    module_print("Phase 3: send aux area")
    dev.send_file(bootimg.auxcode, bootimg.auxcode_addr)
    module_print("Phase 4: decrypt aux area")
    dev.decrypt()
    module_print("Phase 5: send bootreg0.bin")
    dev.send_file(bootimg.bootreg_def, bootimg.bootregs_addr)
    module_print("Phase 6: send fastboot image")
    dev.send_file(bootimg.image, 0)
    module_print("End: Stop all threads")
    dev.reader_thr.stop()
    dev.reader_thr.join()
    if terminal:
        module_print("Use Ctrl+] to exit, Ctrl+H Ctrl+T shows help")
        term = serial.tools.miniterm.Miniterm(dev.dev, eol="lf")
        term.set_tx_encoding("utf-8")
        term.set_rx_encoding("utf-8")
        click.echo(dev.dev.read_all())
        term.start()
        term.join()
    return None


if __name__ == "__main__":
    cli()
