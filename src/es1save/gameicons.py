# Copyright (C) 2026 KiasuBurger
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Reads the game's icons out of its textures (cooked Texture2D assets, UE 4.17).

The blueprint of each item and resource names its icon, for example
'/Game/UI/HUD/Images/Equipment/equip_dev_energy_shield.equip_dev_energy_shield'. That icon is
a texture in the .pak files, in a .uasset and a .uexp. The .uexp holds the texture's
properties, and then its pixels in each pixel format that the cooked game has:

    SizeX, SizeY, NumSlices (int32)  PixelFormat (string, 'PF_B8G8R8A8')
    FirstMip, NumMips (int32)
    for each mip: bCooked (int32)  bulk data flags, element count, size (int32)
                  offset (int64)   the pixels, if they are inline   SizeX, SizeY (int32)

The game's icons are all PF_B8G8R8A8: 4 bytes a pixel, not compressed, with one mip that is
inline. This module reads only that format, so it does not need numpy.

    texture_name(ref)          'UI/HUD/Images/Equipment/equip_dev_energy_shield' for the example
    read_texture(uexp)         (width, height, RGBA bytes), or None
    png(width, height, rgba)   the bytes of a PNG file
    read_icons(game, names)    yields (name, PNG bytes) for each texture name that it can read
"""

import re
import struct
import zlib
from collections.abc import Callable, Iterable, Iterator

from . import pak

CONTENT = 'RSG/Content/'
GAME = '/Game/'
INLINE = 0x40  # the bulk data flag for pixels that follow their header
SEPARATE = 0x01 | 0x100  # the flags for pixels at the end of the file or in a .ubulk file
_FORMAT = re.compile(rb'PF_[A-Za-z0-9_]+\x00')


def texture_name(ref: str | None) -> str | None:
    """The path of a texture below /Game/, without the object name, from a reference to it.
    None if ref is not a reference to an asset in /Game/."""
    if not ref or not ref.startswith(GAME):
        return None
    return ref[len(GAME) :].split('.', 1)[0] or None


def read_texture(uexp: bytes) -> tuple[int, int, bytes] | None:
    """The width, height and RGBA pixels of mip 0 of the texture in a .uexp. None if it is
    not a texture, or if its pixels are not PF_B8G8R8A8 and inline."""
    for m in _FORMAT.finditer(uexp):
        start = m.start() - 4
        if start < 12 or struct.unpack_from('<i', uexp, start)[0] != len(m.group()):
            continue
        width, height, slices = struct.unpack_from('<3i', uexp, start - 12)
        if m.group() != b'PF_B8G8R8A8\x00' or slices != 1 or not (0 < width <= 4096 and 0 < height <= 4096):
            continue
        p = m.end()
        try:
            _first, mips, _cooked, flags, count, size = struct.unpack_from('<6i', uexp, p)
        except struct.error:
            return None
        p += 24 + 8  # and the offset
        need = width * height * 4
        if mips < 1 or flags & SEPARATE or not flags & INLINE or count != need or size != need:
            return None
        bgra = uexp[p : p + need]
        if len(bgra) != need:
            return None
        rgba = bytearray(bgra)
        rgba[0::4], rgba[2::4] = bgra[2::4], bgra[0::4]
        return width, height, bytes(rgba)
    return None


def png(width: int, height: int, rgba: bytes) -> bytes:
    """The bytes of an RGBA PNG file of the pixels."""
    stride = width * 4
    raw = b''.join(b'\0' + rgba[y * stride : (y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))

    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw, 6))
        + chunk(b'IEND', b'')
    )


def read_icons(
    game: str, names: Iterable[str], progress: Callable[[int, int], object] | None = None
) -> Iterator[tuple[str, bytes]]:
    """Yields (name, PNG bytes) for each texture in `names` (from texture_name). It leaves out
    the textures that the game does not have and those that read_texture cannot read. It calls
    progress with (done, total) after each texture."""
    wanted = set(names)
    files = pak.read_files(game, CONTENT, lambda rest: rest.endswith('.uexp') and rest[: -len('.uexp')] in wanted)
    for done, (rest, data) in enumerate(sorted(files.items()), 1):
        texture = read_texture(data)
        if texture:
            yield rest[: -len('.uexp')], png(*texture)
        if progress:
            progress(done, len(files))
