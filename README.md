# A series of scripts for HiSTB SoCs

# Usage

## serial\_boot.py
see `./serial_boot.py -h` 
commonly used to boot fastboot.bin from serial, for recovery the board.

## extract\_uboot.py
extract essetial binaries to compile `l-loader`

# Installation

## apt
```bash
sudo apt install -y python3-serial python3-click python3-crcmod python3-tqdm
```

## pip
```bash
# It's recommended to create a virtual environment first
pip install -r requirements.txt
```

# License
GPL-2.0-or-later
