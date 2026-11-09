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

"""Reads the default values of a cooked blueprint (.uasset and .uexp, UE 4.17).

A cooked package has a header in the .uasset and the data of its objects in the .uexp. The
header holds a name table, the objects that the package imports, and the objects that it holds. The editor needs only the
class default object (Default__<Name>_C) of each item's blueprint. Its tagged properties
give the item's name, description, category and stats. A blueprint keeps only the values
that are different from its parent blueprint, so `parent` names the blueprint to read next.

    asset = Asset(uasset_bytes, uexp_bytes)
    asset.defaults()      {property: value} of the class default object
    asset.components()    {name: {property: value}} of the components of the blueprint
    asset.parent          class name of the parent blueprint, e.g. 'BP_Device_Shield_001_C'

Values: numbers, bools and strings as they are. An enum is 'EType::Value'. An object
reference is its path. A text is the (namespace, key, source string) of its localisation.
A struct is a dict of its properties, and a struct that the engine stores in binary is a
tuple of numbers. A value of a type that is not known here is None.
"""

import struct
from typing import Any

TAG = 0x9E2A83C1
NATIVE = {  # struct name -> struct format of the values that the engine stores in binary
    'Vector': '<3f',
    'Rotator': '<3f',
    'Vector2D': '<2f',
    'LinearColor': '<4f',
    'Color': '<4B',
    'IntPoint': '<2i',
    'Guid': '<4I',
}


class AssetError(ValueError):
    pass


class _Reader:
    def __init__(self, data: bytes, p: int = 0) -> None:
        self.d = data
        self.p = p

    def take(self, fmt: str) -> Any:
        v = struct.unpack_from(fmt, self.d, self.p)
        self.p += struct.calcsize(fmt)
        return v[0] if len(v) == 1 else v

    def i32(self) -> int:
        return int(self.take('<i'))

    def skip(self, n: int) -> None:
        self.p += n

    def string(self) -> str:
        n = self.i32()
        if n < 0:
            s = self.d[self.p : self.p - 2 * n - 2].decode('utf-16-le')
            self.p -= 2 * n
            return s
        s = self.d[self.p : self.p + n - 1].decode('latin-1')
        self.p += n
        return s


class Asset:
    def __init__(self, uasset: bytes, uexp: bytes = b'') -> None:
        self.data = uasset + uexp
        try:
            self._read_summary()
        except (struct.error, IndexError, UnicodeDecodeError) as e:
            raise AssetError('damaged package header (%s)' % e) from None

    def _read_summary(self) -> None:
        r = _Reader(self.data)
        if r.take('<I') != TAG:
            raise AssetError('not a package')
        legacy = r.i32()
        if legacy != -7:
            raise AssetError('package file version %d, which this reader cannot read' % legacy)
        r.skip(4)  # the UE3 version
        self.version = r.i32()
        r.skip(4)  # the licensee version
        r.skip(20 * r.i32())  # custom versions: a GUID and a version each
        r.skip(4)  # total header size
        r.string()  # folder name
        r.skip(4)  # package flags
        names, names_at = r.i32(), r.i32()
        r.skip(8)  # gatherable text data
        exports, exports_at, imports, imports_at = r.i32(), r.i32(), r.i32(), r.i32()
        r.p = names_at
        self.names = []
        for _ in range(names):
            self.names.append(r.string())
            r.skip(4)  # the two hashes of the name
        r.p = imports_at
        self.imports = []
        for _ in range(imports):
            r.skip(16)  # the class package and class name
            outer = r.i32()
            self.imports.append((outer, self.name(r)))
        r.p = exports_at
        self.exports = []
        for _ in range(exports):
            cls, parent, _template, outer = r.take('<4i')
            name = self.name(r)
            r.skip(4)  # object flags
            size, offset = r.take('<2q')
            r.skip(12 + 16 + 4 + 4 + 4 + 4 + 16)  # the flags, GUID and dependencies of the export
            self.exports.append(
                {'class': cls, 'parent': parent, 'outer': outer, 'name': name, 'size': size, 'offset': offset}
            )

    def name(self, r: _Reader) -> str:
        index, number = r.take('<2i')
        if not 0 <= index < len(self.names):
            raise AssetError('name %d of %d' % (index, len(self.names)))
        name = self.names[index]
        return name if number == 0 else '%s_%d' % (name, number - 1)

    def object_name(self, index: int) -> str | None:
        """The name of an imported (negative) or exported (positive) object."""
        if index < 0:
            return self.imports[-index - 1][1]
        if index > 0:
            return str(self.exports[index - 1]['name'])
        return None

    def object_path(self, index: int) -> str | None:
        """The full path of an imported object, or the name of an exported one."""
        if index >= 0:
            return self.object_name(index)
        parts = []
        while index < 0:
            outer, name = self.imports[-index - 1]
            parts.append(name)
            index = outer
        return '.'.join(reversed(parts))

    @property
    def generated_class(self) -> dict[str, Any] | None:
        """The export of the blueprint's class, which says what the parent class is."""
        return next((e for e in self.exports if self.object_name(e['class']) == 'BlueprintGeneratedClass'), None)

    @property
    def parent(self) -> str | None:
        cls = self.generated_class
        return self.object_name(cls['parent']) if cls else None

    def defaults(self) -> dict[str, Any]:
        """The properties of the class default object, or none if the package has none."""
        cdo = next((e for e in self.exports if str(e['name']).startswith('Default__')), None)
        if cdo is None:
            return {}
        try:
            return self._properties(_Reader(self.data, cdo['offset']))
        except (struct.error, IndexError, UnicodeDecodeError) as e:
            raise AssetError('damaged default object (%s)' % e) from None

    def components(self) -> dict[str, dict[str, Any]]:
        """The properties of each component of the blueprint, by name: for example the
        WeaponComponent of a ship. A component that a C++ class makes is inside the class
        default object. A component that a parent blueprint adds is a template inside the
        class. A blueprint keeps only the values that are different from its parent."""
        owners = {
            i
            for i, e in enumerate(self.exports, 1)
            if e is self.generated_class or str(e['name']).startswith('Default__')
        }
        out = {}
        for e in self.exports:
            if e['outer'] not in owners or not (self.object_name(e['class']) or '').endswith('Component'):
                continue
            try:
                out[str(e['name'])] = self._properties(_Reader(self.data, e['offset']))
            except (struct.error, IndexError, UnicodeDecodeError) as ex:
                raise AssetError('damaged component %s (%s)' % (e['name'], ex)) from None
        return out

    # ---- tagged properties

    def _properties(self, r: _Reader) -> dict[str, Any]:
        out: dict[str, Any] = {}
        while True:
            name = self.name(r)
            if name == 'None':
                return out
            kind = self.name(r)
            size, index = r.take('<2i')
            extra: Any = None
            if kind == 'StructProperty':
                extra = self.name(r)
                r.skip(16)
            elif kind == 'BoolProperty':
                extra = r.take('<B')
            elif kind in ('ByteProperty', 'EnumProperty', 'ArrayProperty', 'SetProperty'):
                extra = self.name(r)
            elif kind == 'MapProperty':
                extra = (self.name(r), self.name(r))
            if r.take('<B'):
                r.skip(16)  # the property's GUID
            start = r.p
            value = self._value(r, kind, size, extra)
            r.p = start + size
            out[name if index == 0 else '%s[%d]' % (name, index)] = value

    def _value(self, r: _Reader, kind: str, size: int, extra: Any) -> Any:
        if kind == 'BoolProperty':
            return bool(extra)
        if kind == 'IntProperty':
            return r.i32()
        if kind == 'FloatProperty':
            return r.take('<f')
        if kind in ('NameProperty', 'EnumProperty'):
            return self.name(r)
        if kind == 'ByteProperty':
            return r.take('<B') if size == 1 else self.name(r)
        if kind == 'StrProperty':
            return r.string()
        if kind in ('ObjectProperty', 'ClassProperty'):
            return self.object_path(r.i32())
        if kind == 'TextProperty':
            return self._text(r)
        if kind == 'StructProperty':
            if extra in NATIVE:
                return r.take(NATIVE[extra])
            return self._properties(r)
        if kind == 'ArrayProperty':
            return self._array(r, size, extra)
        return None

    def _array(self, r: _Reader, size: int, inner: str) -> list[Any]:
        n = r.i32()
        if inner == 'StructProperty':
            # one tag for all the elements, which then follow without tags
            self.name(r)
            self.name(r)
            r.skip(8)
            struct_name = self.name(r)
            r.skip(17)
            if struct_name in NATIVE:
                return [r.take(NATIVE[struct_name]) for _ in range(n)]
            return [self._properties(r) for _ in range(n)]
        if inner == 'BoolProperty':
            return [bool(r.take('<B')) for _ in range(n)]
        if inner in ('ByteProperty', 'EnumProperty'):
            if n and (size - 4) // n == 8:
                return [self.name(r) for _ in range(n)]
            return list(r.take('<%dB' % n)) if n > 1 else [r.take('<B')] * n
        return [self._value(r, inner, 4, None) for _ in range(n)]

    def _text(self, r: _Reader) -> tuple[str, str, str] | str | None:
        r.skip(4)  # flags
        history = r.take('<b')
        if history == 0:  # a localised text: namespace, key, source string
            return r.string(), r.string(), r.string()
        if history == -1:  # no localisation, and maybe a string that does not change
            return r.string() if r.i32() else ''
        return None
