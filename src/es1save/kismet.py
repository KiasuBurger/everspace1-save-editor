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

"""Reads the Kismet bytecode of the functions of a cooked blueprint (UE 4.17).

A blueprint keeps the code of each of its functions as bytecode in the export of the
function. attributes.py runs this code to calculate the attributes of an item as the game
does: GetEquipmentAttributeValue of the items, and OnInstall of the mods.

    functions(asset)     {function name: {'params': [[name, out]], 'code': [[offset, node], ...]}}

A node is a list whose first element names it:

    ['local', name] ['self', name] ['default', name]   a variable of the frame, of the
                                                       object, or of the class default object
    ['ctx', object, node]                              node, evaluated on another object
    ['member', name, node]                             a member of a struct
    ['let', target, value]
    ['call', function, [args]]                         a call of a function by its object
                                                       ('Class.Function')
    ['vcall', name, [args]]                            a call by name, on the object
    ['const', value] ['obj', name] ['selfobj'] ['none']
    ['cast', class, node] ['pcast', type, node]
    ['switch', index, [[value, result], ...], default]
    ['array', [nodes]] ['struct', name, [nodes]] ['setarray', target, [nodes]]
    ['index', array, index]                            an element of an array
    ['jump', offset] ['jumpifnot', offset, cond] ['return', node]
    ['push', offset] ['pop'] ['popifnot', cond] ['computedjump', node]
    ['nothing'] ['end'] ['unknown', text]

An offset is the position of a statement in memory, where an object pointer takes 8 bytes
and a name takes 12. The jumps use these offsets, not the positions in the file.
"""

import struct
from typing import Any

from .uasset import Asset

Node = list[Any]

# EX_ values of the opcodes that this reader knows
_PTR_ONLY = {0x00: 'local', 0x01: 'self', 0x02: 'default', 0x48: 'local'}


class KismetError(ValueError):
    pass


class _Reader:
    def __init__(self, asset: Asset, start: int, end: int) -> None:
        self.a = asset
        self.d = asset.data
        self.p = start
        self.end = end
        self.mem = 0

    def take(self, fmt: str, mem: int | None = None) -> Any:
        values = struct.unpack_from(fmt, self.d, self.p)
        size = struct.calcsize(fmt)
        self.p += size
        self.mem += size if mem is None else mem
        return values if len(values) > 1 else values[0]

    def u8(self) -> int:
        return int(self.take('<B'))

    def peek(self) -> int:
        return self.d[self.p]

    def ptr(self) -> str | None:
        """An object, by its name. An imported function is 'Class.Function', so that the
        class it belongs to is known."""
        index = self.take('<i', 8)
        if not index:
            return None
        if index < 0:
            parts = (self.a.object_path(index) or '').split('.')
            if len(parts) > 2:
                return '.'.join(parts[-2:])
            return parts[-1]
        return self.a.object_name(index)

    def var(self) -> str | None:
        """A variable or a class, by its name alone."""
        name = self.ptr()
        return name.rsplit('.', 1)[-1] if name else None

    def name(self) -> str:
        index, number = self.take('<2i', 12)
        if not 0 <= index < len(self.a.names):
            raise KismetError('name %d' % index)
        name = self.a.names[index]
        return name if number == 0 else '%s_%d' % (name, number - 1)

    def cstring(self, width: int) -> str:
        start = self.p
        while self.d[self.p : self.p + width] != b'\0' * width:
            self.p += width
        text = self.d[start : self.p].decode('latin-1' if width == 1 else 'utf-16-le')
        self.p += width
        self.mem += self.p - start
        return text


def _args(r: _Reader) -> list[Node]:
    out = []
    while r.peek() != 0x16:
        out.append(_expr(r))
    r.u8()
    return out


def _until(r: _Reader, stop: int) -> list[Node]:
    out = []
    while r.peek() != stop:
        out.append(_expr(r))
    r.u8()
    return out


def _expr(r: _Reader) -> Node:
    op = r.u8()
    if op in _PTR_ONLY:
        return [_PTR_ONLY[op], r.var()]
    if op == 0x04:
        return ['return', _expr(r)]
    if op == 0x06:
        return ['jump', r.take('<I')]
    if op == 0x07:
        target = r.take('<I')
        return ['jumpifnot', target, _expr(r)]
    if op == 0x09:
        r.take('<HB')
        return ['nothing', _expr(r)]
    if op == 0x0B:
        return ['nothing']
    if op == 0x0F:
        r.ptr()
        target = _expr(r)
        return ['let', target, _expr(r)]
    if op in (0x14, 0x43, 0x44, 0x5F, 0x60):
        target = _expr(r)
        return ['let', target, _expr(r)]
    if op in (0x12, 0x19, 0x1A):
        obj = _expr(r)
        r.take('<I')
        r.ptr()
        return ['ctx', obj, _expr(r)]
    if op == 0x13:
        cls = r.var()
        return ['cast', cls, _expr(r)]
    if op == 0x15:
        return ['nothing']
    if op == 0x17:
        return ['selfobj']
    if op == 0x18:
        r.take('<I')
        return _expr(r)
    if op in (0x1B, 0x45):
        name = r.name()
        return ['vcall', name, _args(r)]
    if op in (0x1C, 0x46, 0x68):
        func = r.ptr()
        return ['call', func, _args(r)]
    if op == 0x1D:
        return ['const', r.take('<i')]
    if op == 0x1E:
        return ['const', r.take('<f')]
    if op == 0x1F:
        return ['const', r.cstring(1)]
    if op == 0x34:
        return ['const', r.cstring(2)]
    if op == 0x20:
        return ['obj', r.var()]
    if op == 0x21:
        return ['const', r.name()]
    if op == 0x22:
        return ['const', list(r.take('<3i'))]
    if op == 0x23:
        return ['const', list(r.take('<3f'))]
    if op in (0x24, 0x2C):
        return ['const', r.u8()]
    if op == 0x25:
        return ['const', 0]
    if op == 0x26:
        return ['const', 1]
    if op == 0x27:
        return ['const', True]
    if op == 0x28:
        return ['const', False]
    if op == 0x29:
        kind = r.u8()
        if kind == 0:
            return ['const', '']
        parts = [_expr(r) for _ in range(3 if kind == 1 else 1)]
        return parts[0]
    if op in (0x2A, 0x2D):
        return ['none']
    if op == 0x2B:
        return ['const', list(r.take('<10f'))]
    if op == 0x2E:
        cls = r.var()
        return ['cast', cls, _expr(r)]
    if op == 0x2F:
        struct_name = r.var()
        r.take('<i')
        return ['struct', struct_name, _until(r, 0x30)]
    if op == 0x31:
        target = _expr(r)
        return ['setarray', target, _until(r, 0x32)]
    if op == 0x35:
        return ['const', r.take('<q')]
    if op == 0x36:
        return ['const', r.take('<Q')]
    if op == 0x38:
        kind = r.u8()
        return ['pcast', kind, _expr(r)]
    if op == 0x42:
        prop = r.var()
        return ['member', prop, _expr(r)]
    if op == 0x4C:
        return ['push', r.take('<I')]
    if op == 0x4D:
        return ['pop']
    if op == 0x4E:
        return ['computedjump', _expr(r)]
    if op == 0x4F:
        return ['popifnot', _expr(r)]
    if op in (0x50, 0x5A, 0x5E):
        return ['nothing']
    if op == 0x51:
        return _expr(r)
    if op in (0x52, 0x54, 0x55):
        r.ptr()
        return _expr(r)
    if op == 0x53:
        return ['end']
    if op == 0x5B:
        return ['const', r.take('<I')]
    if op in (0x5C, 0x62):
        target = _expr(r)
        return ['unknown', 'delegate', target, _expr(r)]
    if op == 0x5D:
        return ['unknown', 'delegate', _expr(r)]
    if op == 0x61:
        r.name()
        target = _expr(r)
        return ['unknown', 'bind', target, _expr(r)]
    if op == 0x63:
        r.ptr()
        return ['unknown', 'multicast', _args(r)]
    if op == 0x64:
        r.ptr()
        return ['unknown', 'persistent', _expr(r)]
    if op == 0x65:
        r.ptr()
        r.take('<i')
        return ['array', _until(r, 0x66)]
    if op == 0x6B:
        array = _expr(r)
        return ['index', array, _expr(r)]
    if op == 0x69:
        count = r.take('<H')
        r.take('<I')
        index = _expr(r)
        cases = []
        for _ in range(count):
            value = _expr(r)
            r.take('<I')
            cases.append([value, _expr(r)])
        return ['switch', index, cases, _expr(r)]
    raise KismetError('opcode 0x%02x' % op)


PARM = 0x80
OUT_PARM = 0x100
RETURN_PARM = 0x400


def _params(asset: Asset, child: int) -> list[list[Any]]:
    """The parameters of a function, in order, from its first child property: [name, whether
    it is an out parameter] for each.
    Each property export starts with the end of its tagged properties, a flag, Next,
    ArrayDim and the property flags."""
    out = []
    seen = set()
    while child > 0 and child not in seen:
        seen.add(child)
        export = asset.exports[child - 1]
        p = int(export['offset']) + 8 + 4
        (following,) = struct.unpack_from('<i', asset.data, p)
        (flags,) = struct.unpack_from('<Q', asset.data, p + 8)
        if flags & PARM and not flags & RETURN_PARM:
            out.append([str(export['name']), bool(flags & OUT_PARM)])
        child = following
    return out


def functions(asset: Asset) -> dict[str, dict[str, Any]]:
    """The functions of the blueprint: for each, 'params', [name, is out] of its parameters
    in order, and 'code', [offset, node] for each statement. A function that this reader cannot
    read is left out."""
    out = {}
    for export in asset.exports:
        if asset.object_name(export['class']) != 'Function':
            continue
        p = int(export['offset'])
        try:
            index = struct.unpack_from('<i', asset.data, p)[0]
            if asset.names[index] != 'None':
                continue  # a function with tagged properties, which the game's do not have
            p += 8 + 4 * 3  # the end of the properties, a flag, Next, SuperStruct
            (children,) = struct.unpack_from('<i', asset.data, p)
            p += 4
            disk = struct.unpack_from('<2i', asset.data, p)[1]
            p += 8
            r = _Reader(asset, p, p + disk)
            code = []
            while r.p < r.end:
                at = r.mem
                code.append([at, _expr(r)])
            out[str(export['name'])] = {'params': _params(asset, children), 'code': code}
        except KismetError, struct.error, IndexError, UnicodeDecodeError:
            continue
    return out
