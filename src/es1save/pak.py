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

"""Reads files out of the game's .pak files.

A .pak holds the files one after another, an index of them, and a footer at the end that
gives the position of the index. The game has its content in several of them
(pakchunk0 to pakchunk6). This game uses version 4 of the format: the index is not
encrypted, and a compressed file is in zlib blocks.

    files = read_files(game, 'RSG/Content/DataFiles/')      {path below that: bytes}

Only what this game needs is here: versions 3 and 4, zlib, and no encryption.
"""

import glob
import os
import struct
import zlib
from collections.abc import Callable
from typing import Self

PAKS = os.path.join('RSG', 'Content', 'Paks')
MAGIC = 0x5A6F12E1
FOOTER = 44  # magic, version, index offset and size, SHA-1 of the index
VERSIONS = (3, 4)
ZLIB = 1


class PakError(ValueError):
    pass


class Entry:
    """Where one file is in the .pak, and how it is stored."""

    __slots__ = ('blocks', 'compression', 'encrypted', 'end', 'offset', 'size', 'uncompressed')

    def __init__(self, data: bytes, p: int) -> None:
        self.offset, self.size, self.uncompressed, self.compression = struct.unpack_from('<qqqi', data, p)
        p += 28 + 20  # and the SHA-1 of the file
        self.blocks: list[tuple[int, int]] = []
        if self.compression:
            (n,) = struct.unpack_from('<i', data, p)
            p += 4
            self.blocks = [struct.unpack_from('<qq', data, p + 16 * i) for i in range(n)]
            p += 16 * n
        self.encrypted = data[p]
        self.end = p + 5  # and the size of a compression block

    @property
    def header(self) -> int:
        """The size of the copy of the entry that comes before the file's data."""
        return 28 + 20 + (4 + 16 * len(self.blocks) if self.compression else 0) + 5


def _string(d: bytes, p: int) -> tuple[str, int]:
    (n,) = struct.unpack_from('<i', d, p)
    p += 4
    if n < 0:
        return d[p : p + 2 * -n - 2].decode('utf-16-le'), p - 2 * n
    return d[p : p + n - 1].decode('latin-1'), p + n


class Pak:
    """One .pak file, open for reading. Names are the full paths below the mount point,
    for example 'RSG/Content/DataFiles/PerkData.csv'."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.f = open(path, 'rb')  # noqa: SIM115 (closed by close() or the with statement)
        try:
            self._read_index()
        except (struct.error, IndexError, UnicodeDecodeError) as e:
            self.f.close()
            raise PakError('%s: damaged index (%s)' % (path, e)) from None
        except PakError:
            self.f.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.f.close()

    def _read_index(self) -> None:
        self.f.seek(0, os.SEEK_END)
        if self.f.tell() < FOOTER:
            raise PakError('%s: too short to be a .pak' % self.path)
        self.f.seek(-FOOTER, os.SEEK_END)
        magic, version, offset, size = struct.unpack('<IIqq', self.f.read(24))
        if magic != MAGIC:
            raise PakError('%s: not a .pak' % self.path)
        if version not in VERSIONS:
            raise PakError('%s: .pak version %d, which this reader cannot read' % (self.path, version))
        self.f.seek(offset)
        index = self.f.read(size)
        mount, p = _string(index, 0)
        # the mount point is relative to the engine's binaries: '../../../' is the game's root
        self.mount = mount.replace('../', '')
        (count,) = struct.unpack_from('<i', index, p)
        p += 4
        self.entries: dict[str, Entry] = {}
        for _ in range(count):
            name, p = _string(index, p)
            entry = Entry(index, p)
            p = entry.end
            self.entries[self.mount + name] = entry

    def read(self, name: str) -> bytes:
        entry = self.entries[name]
        if entry.encrypted:
            raise PakError('%s: %s is encrypted' % (self.path, name))
        if not entry.compression:
            self.f.seek(entry.offset + entry.header)
            return self.f.read(entry.size)
        if entry.compression != ZLIB:
            raise PakError('%s: %s has compression method %d' % (self.path, name, entry.compression))
        out = bytearray()
        for start, end in entry.blocks:
            self.f.seek(start)
            out += zlib.decompress(self.f.read(end - start))
        if len(out) != entry.uncompressed:
            raise PakError('%s: %s has %d bytes, not %d' % (self.path, name, len(out), entry.uncompressed))
        return bytes(out)


def pak_files(game: str) -> list[str]:
    """The game's .pak files, in name order."""
    return sorted(glob.glob(os.path.join(game, PAKS, '*.pak')))


def read_files(game: str, prefix: str, wanted: Callable[[str], object] | None = None) -> dict[str, bytes]:
    """The files whose path starts with prefix, from all of the game's .pak files, keyed by
    the rest of the path. With `wanted`, only the files for which it is true. A file in more
    than one .pak comes from the last one, as the game would load it."""
    files = pak_files(game)
    if not files:
        raise PakError('no .pak files in %s' % os.path.join(game, PAKS))
    out = {}
    for path in files:
        with Pak(path) as pak:
            for name in pak.entries:
                if name.startswith(prefix):
                    rest = name[len(prefix) :]
                    if wanted is None or wanted(rest):
                        out[rest] = pak.read(name)
    return out
