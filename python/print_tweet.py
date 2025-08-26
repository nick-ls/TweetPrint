#!/usr/bin/env python3
# Uses PIL to make a tweet graphic, then rasterizes and prints it
import os
import sys
import time
from PIL import Image, ImageDraw, ImageFont

DEV = "/dev/usb/lp0"
WIDTH = 384  # printer width in pixels

# Bayer matrix
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
    threshold = int(BAYER8[y % 8][x % 8] * (255.0 / 64.0))
    return 1 if gray < threshold else 0
def wrap_text_pixels(text, font, max_width):
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = current_line + (" " if current_line else "") + word
        # measure width of test_line
        bbox = ImageDraw.Draw(Image.new("L", (1,1))).textbbox((0,0), test_line, font=font)
        line_width = bbox[2] - bbox[0]
        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines

def build_bitmap_from_image(img):
    img = img.convert("L")  # grayscale
    width, height = img.size
    pad = (8 - (width % 8)) % 8
    width_padded = width + pad
    bytes_per_row = width_padded // 8

    data = bytearray()
    pixels = img.load()
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
def render_tweet(profile_path, username, text, date):
    # Load and resize profile image
    pimg = Image.open(profile_path).convert("L")
    aspect = pimg.width / pimg.height
    target_h = 40
    target_w = int(aspect * target_h)
    pimg = pimg.resize((target_w, target_h))

    # Fonts
    try:
        font_user = ImageFont.truetype("DejaVuSans-Bold.ttf", 24)
        font_text = ImageFont.truetype("DejaVuSans.ttf", 22)
        font_date = ImageFont.truetype("DejaVuSans.ttf", 18)
    except:
        font_user = ImageFont.load_default()
        font_text = ImageFont.load_default()
        font_date = ImageFont.load_default()

    # Wrap tweet text
    lines = wrap_text_pixels(text, font_text, WIDTH);

    # Dummy draw to measure
    dummy = Image.new("L", (1,1))
    draw_dummy = ImageDraw.Draw(dummy)

    # Profile + username line height
    username_bbox = draw_dummy.textbbox((0,0), "@"+username, font=font_user)
    profile_line_height = max(target_h, username_bbox[3])

    # Tweet text block height
    line_bboxes = [draw_dummy.textbbox((0,0), line, font=font_text) for line in lines]
    tweet_text_height = sum([bbox[3]-bbox[1]+4 for bbox in line_bboxes])

    # Date height
    date_bbox = draw_dummy.textbbox((0,0), date, font=font_date)
    date_height = date_bbox[3]-date_bbox[1]

    # Total canvas height — only change: increase bottom padding
    padding_top = 8
    padding_bottom = 40  # previously 8
    spacing = 10
    total_height = padding_top + profile_line_height + spacing + tweet_text_height + spacing + date_height + padding_bottom

    # Create canvas
    img = Image.new("L", (WIDTH, total_height), 255)
    draw = ImageDraw.Draw(img)

    # Paste profile
    img.paste(pimg, (0, padding_top))

    # Draw username
    draw.text((target_w + 6, padding_top), "@"+username, font=font_user, fill=0)

    # Draw tweet text
    y_offset = padding_top + profile_line_height + spacing
    for line, bbox in zip(lines, line_bboxes):
        draw.text((0, y_offset), line, font=font_text, fill=0)
        y_offset += (bbox[3]-bbox[1]) + 4  # exact line height + spacing

    # Draw date below
    y_offset_date = y_offset + spacing
    draw.text((0, y_offset_date), date, font=font_date, fill=0)

    return img

def main():
    if len(sys.argv) < 5:
        print("Usage: tweetprint.py <profile_img> <username> <tweet_text> <date>")
        sys.exit(1)

    profile_path, username, tweet_text, date = sys.argv[1:5]

    img = render_tweet(profile_path, username, tweet_text, date)
    data, width_bytes, height = build_bitmap_from_image(img)

    print("Rendering tweet:", username)
    print("Width:", WIDTH, "Bytes/row:", width_bytes, "Height:", height)

    try:
        send_to_printer(DEV, data, width_bytes, height)
        print("Printed OK.")
    except Exception as e:
        print("Print failed:", e)

if __name__ == "__main__":
    main()

