#!/usr/bin/python3
# SPDX-License-Specifier: GPL-2.0-or-later
# Copyright 2023 Yang Xiwen

# Extract essential binaries from stock u-boot
# AUXCODE.img, BOOT[0-2].reg etc

import click
import os
from image import FastbootImageV1


@click.command()
@click.argument("filename", type=click.File("rb"), required=True)
@click.option("-p", "--print", "p", type=bool, required=False, default=False, is_flag=True, help="print image info")
@click.option("-d", "--path", "d", type=click.Path(), required=False, default=".", show_default=True, help="set the output path of the images")
@click.option("-e", "--strip", "e", type=bool, required=False, default=False, is_flag=True, help="strip the suffix 0s to minimize the image size")
def extract(filename, p, d, e):
    """
    A tool to extract some essential binaries for l-loader from stock firmware
    """
    i = FastbootImageV1(filename)
    i.parse_image()
    i.extract_images()
    if e:
        i.truncate_to_minimal()
    i.write_to_directory(d)
    if p:
        click.echo(i)
    return None

if __name__ == '__main__':
    extract();
