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

# Note
- supports only non-CA SoCs. (This repo will not work if CA is enabled)
- supports only fastboot.bin version 1. (Most Hi3798xxx SoCs fall into this category)

# Tested SoCs
- Hi3798MV200
- Hi3798MV300
Most Hi3798xxx SoCs should also work

# License
GPL-2.0-or-later
