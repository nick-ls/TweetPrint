#!/usr/bin/env python3
# Rasterizes and prints an image to the printer
import os
import sys
import time
from PIL import Image

DEV = "/dev/usb/lp0"
WIDTH = 384   # printer width in pixels

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

def dither_pixel(gray, x, y):
	"""
	Return 1=black, 0=white using Bayer 8x8 ordered dither.
	gray: 0 (black) ... 255 (white)
	"""
	threshold = int(BAYER8[y % 8][x % 8] * (255.0 / 64.0))
	# Darker than threshold = black
	return 1 if gray < threshold else 0

def build_bitmap_from_image(img):
	# convert to grayscale
	img = img.convert("L")

	# resize to printer width, keep aspect ratio
	w, h = img.size
	new_h = int(h * (WIDTH / float(w)))
	img = img.resize((WIDTH, new_h), Image.LANCZOS)

	width = img.width
	height = img.height

	# pad width to multiple of 8
	pad = (8 - (width % 8)) % 8
	width_padded = width + pad
	bytes_per_row = width_padded // 8

	pixels = img.load()
	data = bytearray()

	for y in range(height):
		row_bits = []
		for x in range(width_padded):
			if x < width:
				gray = pixels[x, y]
				b = dither_pixel(gray, x, y)
			else:
				b = 0
			row_bits.append(b)
		for byte_i in range(bytes_per_row):
			val = 0
			for bit in range(8):
				val <<= 1
				val |= row_bits[byte_i * 8 + bit]
			data.append(val & 0xFF)
	return data, bytes_per_row, height

def send_to_printer(dev, data_bytes, width_bytes, height_pixels):
	INIT = b'\x1b\x40'
	m = 0
	xL = width_bytes & 0xFF
	xH = (width_bytes >> 8) & 0xFF
	yL = height_pixels & 0xFF
	yH = (height_pixels >> 8) & 0xFF
	header = bytes([0x1d, 0x76, 0x30, m, xL, xH, yL, yH])

	with open(dev, "wb", buffering=0) as f:
		f.write(b'\n')
		f.flush()
		time.sleep(0.02)

		f.write(INIT + header)
		f.flush()
		time.sleep(0.02)

		f.write(data_bytes)
		f.flush()

	return True

def main():
	if len(sys.argv) < 2:
		print("Usage: {} <imagefile>".format(sys.argv[0]))
		return

	image_path = sys.argv[1]
	if not os.path.exists(image_path):
		print("Image", image_path, "not found.")
		return

	img = Image.open(image_path)
	data, width_bytes, height = build_bitmap_from_image(img)
	print("Width px:", WIDTH, "Bytes/row:", width_bytes, "Height px:", height)

	if not os.path.exists(DEV):
		print("Device", DEV, "not found.")
		return

	try:
		send_to_printer(DEV, data, width_bytes, height)
		print("Sent OK.")
	except Exception as e:
		print("Write failed:", e)

if __name__ == "__main__":
	main()

