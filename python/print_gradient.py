#!/usr/bin/env python3
# Prints a few lines of gradient from light on the left to dark on the right
import os
import time

DEV = "/dev/usb/lp0"
WIDTH = 384
HEIGHT = 200

BAYER8 = [
    [0,48,12,60,3,51,15,63],
    [32,16,44,28,35,19,47,31],
    [8,56,4,52,11,59,7,55],
    [40,24,36,20,43,27,39,23],
    [2,50,14,62,1,49,13,61],
    [34,18,46,30,33,17,45,29],
    [10,58,6,54,9,57,5,53],
    [42,26,38,22,41,25,37,21],
]

def pixel_black(x, y, width):
    gray = int((x / (width - 1)) * 255)
    t = int((BAYER8[y % 8][x % 8] + 0.5) * (255.0 / 64.0))
    return 1 if gray > t else 0

def build_bitmap(width, height):
    pad = (8 - (width % 8)) % 8
    width_padded = width + pad
    bytes_per_row = width_padded // 8
    data = bytearray()
    for y in range(height):
        row_bits = []
        for x in range(width_padded):
            b = pixel_black(x, y, width) if x < width else 0
            row_bits.append(b)
        for byte_i in range(bytes_per_row):
            val = 0
            for bit in range(8):
                val <<= 1
                val |= row_bits[byte_i * 8 + bit]
            data.append(val & 0xFF)
    return data, bytes_per_row

def send_to_printer(dev, data_bytes, width_bytes, height_pixels):
    INIT = b'\x1b\x40'

    m = 0
    xL = width_bytes & 0xFF
    xH = (width_bytes >> 8) & 0xFF
    yL = height_pixels & 0xFF
    yH = (height_pixels >> 8) & 0xFF
    header = bytes([0x1d, 0x76, 0x30, m, xL, xH, yL, yH])

    with open(dev, "wb", buffering=0) as f:
        # clear any pending state
        f.write(b'\n')
        f.flush()
        time.sleep(0.02)

        # send init + header in one shot
        f.write(INIT + header)
        f.flush()
        time.sleep(0.02)

        # send raster
        f.write(data_bytes)
        f.flush()

    return True


def main():
    if not os.path.exists(DEV):
        print("Device", DEV, "not found.")
        return
    data, width_bytes = build_bitmap(WIDTH, HEIGHT)
    print("Width px:", WIDTH, "Bytes/row:", width_bytes, "Height px:", HEIGHT)
    try:
        send_to_printer(DEV, data, width_bytes, HEIGHT)
        print("Sent OK.")
    except Exception as e:
        print("Write failed:", e)

if __name__ == "__main__":
    main()

