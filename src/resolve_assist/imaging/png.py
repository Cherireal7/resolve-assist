"""Small, dependency-free PNG decoder (non-interlaced, 8/16-bit).

Used as the fallback when ffmpeg is not installed, and as the decoder for
frames that ffmpeg pipes to us as PNG. Returns a downsampled Image.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from ..color.cdl import RGB

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_DIMENSION = 20_000          # per side
MAX_RAW_BYTES = 1_200_000_000   # decompressed bytes (8K 16-bit RGBA is ~400 MB)

_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PNGError(ValueError):
    pass


@dataclass
class Image:
    width: int            # of the sampled image
    height: int
    pixels: list[RGB]     # floats 0..1, row-major
    source_width: int
    source_height: int


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(ftype: int, row: bytearray, prev: bytearray, bpp: int) -> None:
    n = len(row)
    if ftype == 0:
        return
    if ftype == 1:
        for i in range(bpp, n):
            row[i] = (row[i] + row[i - bpp]) & 0xFF
    elif ftype == 2:
        for i in range(n):
            row[i] = (row[i] + prev[i]) & 0xFF
    elif ftype == 3:
        for i in range(n):
            left = row[i - bpp] if i >= bpp else 0
            row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
    elif ftype == 4:
        for i in range(n):
            left = row[i - bpp] if i >= bpp else 0
            upleft = prev[i - bpp] if i >= bpp else 0
            row[i] = (row[i] + _paeth(left, prev[i], upleft)) & 0xFF
    else:
        raise PNGError(f"bad filter type {ftype}")


def decode_png(data: bytes, max_side: int = 512) -> Image:
    if not data.startswith(PNG_SIGNATURE):
        raise PNGError("not a PNG file")
    pos = len(PNG_SIGNATURE)
    ihdr = None
    palette: list[RGB] = []
    idat = []
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif ctype == b"PLTE":
            palette = [(body[i] / 255, body[i + 1] / 255, body[i + 2] / 255) for i in range(0, len(body) - 2, 3)]
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
    if ihdr is None:
        raise PNGError("missing IHDR")
    width, height, depth, color, _comp, _filt, interlace = ihdr
    if not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION):
        raise PNGError(f"unsupported dimensions {width}x{height}")
    if interlace:
        raise PNGError("interlaced PNG not supported; re-export without interlacing")
    if color not in _CHANNELS:
        raise PNGError(f"unsupported color type {color}")
    if depth not in (8, 16) or (color == 3 and depth != 8):
        raise PNGError(f"unsupported bit depth {depth}; export 8- or 16-bit PNG")
    channels = _CHANNELS[color]
    bpp = channels * depth // 8
    stride = width * bpp
    expected = (stride + 1) * height
    if expected > MAX_RAW_BYTES:
        raise PNGError("image too large to decode safely")

    inflater = zlib.decompressobj()
    raw = inflater.decompress(b"".join(idat), expected + 1)
    if len(raw) < expected:
        raise PNGError("truncated image data")

    step = max(1, -(-max(width, height) // max_side))  # ceil division
    maxval = 255.0 if depth == 8 else 65535.0
    sample_cols = range(0, width, step)
    pixels: list[RGB] = []
    prev = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        row = bytearray(raw[start + 1:start + 1 + stride])
        _unfilter(raw[start], row, prev, bpp)
        prev = row
        if y % step:
            continue
        for x in sample_cols:
            o = x * bpp
            if depth == 8:
                vals = row[o:o + channels]
            else:
                vals = [(row[o + 2 * i] << 8) | row[o + 2 * i + 1] for i in range(channels)]
            if color == 3:
                pixels.append(palette[vals[0]] if vals[0] < len(palette) else (0.0, 0.0, 0.0))
            elif channels >= 3:
                pixels.append((vals[0] / maxval, vals[1] / maxval, vals[2] / maxval))
            else:
                v = vals[0] / maxval
                pixels.append((v, v, v))
    out_w = len(sample_cols)
    out_h = len(pixels) // out_w
    return Image(out_w, out_h, pixels, width, height)


def encode_png(width: int, height: int, pixels: list[RGB], depth: int = 8) -> bytes:
    """Minimal RGB encoder (filter 0). Used for previews and tests."""
    maxval = 255 if depth == 8 else 65535
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for r, g, b in pixels[y * width:(y + 1) * width]:
            for v in (r, g, b):
                q = int(round(min(1.0, max(0.0, v)) * maxval))
                rows.extend(q.to_bytes(depth // 8, "big"))

    def chunk(ctype: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body))

    ihdr = struct.pack(">IIBBBBB", width, height, depth, 2, 0, 0, 0)
    return PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b"")
