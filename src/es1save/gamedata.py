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

"""What the editor knows about the game: its items, resources, perks and glyphs.

All of it comes from the installed game. GameData.build reads it from the .pak files:

    DataFiles/EquipmentData.csv   every item the game gives as loot or blueprint, with its
                                  type (PrimaryWeapon, Device, Mod, ...) and tier
    DataFiles/PerkData.csv        the hangar perks: their levels, costs, icons and what each opens
    DataFiles/GlyphData.inl       the glyphs and enhancements, with their icons
    Blueprints/Equipment, Pickups the default object of each item's blueprint: its name,
                                  description, category, icon, and the mods that fit it
                                  and the code that calculates its attributes (classes)
    Localization/BaseGame_ShortTexts  the names of the attributes and how to show them
    Blueprints/Ships, Framework   the starting loadouts and the default slot counts of each
                                  player ship (see read_loadouts)

The result goes to a JSON file in the cache directory, so the game is read once. A save
names an item by the path of its class, for example
'/Game/Blueprints/Equipment/Devices/BP_Device_Shield_003.BP_Device_Shield_003_C'. The
tables here use the same key.
"""

import csv
import io
import json
import os
import re
import struct
from collections.abc import Callable
from typing import Any

from . import gameicons, gamepaths, kismet, pak, uasset

FORMAT = 9  # of the cache file. A cache of another format is built again.
CONTENT = 'RSG/Content/'
SHIPS = ['Colonial Interceptor', 'Colonial Scout', 'Colonial Gunship', 'Colonial Sentinel']
# The icons of the ships, in the order of SHIPS, from the hall of fame. The game's data does not
# name them. 'tech' is the Sentinel, which the perks call the Tech Fighter.
SHIP_ICONS = ['UI/Images/hall_of_fame_' + name for name in ('interceptor', 'scout', 'gunship', 'tech')]
KINDS = ['PrimaryWeapon', 'SecondaryWeapon', 'Device', 'Consumable', 'Mod', 'Buff']
# The categories that a C++ class of the game sets. The blueprints below such a class do not
# store the category, so the editor gets it from the name of the class.
NATIVE_CATEGORIES = {'ShieldBase': 'Device_Shield'}
# Items that EquipmentData.csv does not list, but that the game gives to the pilot. A Kickstarter
# backer with the special weapon reward gets this laser in loadout A (BP_ShipPlayer.GetLoadOut).
# The game does not give it as a blueprint.
BACKER_ITEMS = {'BP_Weapon_PulseLaser_Kickstarter'}


def class_path(asset: str, name: str | None = None) -> str:
    """The class path a save uses for the blueprint at `asset`, a path below RSG/Content
    without the extension: 'Blueprints/X/BP_Y' gives '/Game/Blueprints/X/BP_Y.BP_Y_C'.
    `name` is the name of the class, when it is known. It can have letters in a different
    case from the file name."""
    return '/Game/%s.%s' % (asset, name or asset.rsplit('/', 1)[-1] + '_C')


def short_name(path: str) -> str:
    """The blueprint name in a class path: 'BP_Device_Shield_003' for the example above."""
    name = path.rsplit('.', 1)[-1]
    return name.removesuffix('_C')


def cache_file() -> str:
    return os.path.join(gamepaths.cache_dir(), 'game_data.json')


def _source(text: Any) -> str:
    """The English source string of a text value from uasset."""
    if isinstance(text, tuple):
        return str(text[2])
    return text if isinstance(text, str) else ''


def _enum_value(value: Any) -> str:
    return str(value).split('::', 1)[-1] if value else ''


# ---- the data files


def parse_equipment_csv(text: str) -> dict[str, dict[str, Any]]:
    """EquipmentData.csv: blueprint name -> {'kind', 'tier', 'random', 'prerequisite'}. The
    second row holds the value of each resource, not an item."""
    rows = list(csv.reader(io.StringIO(text)))
    out = {}
    for row in rows[1:]:
        if len(row) < 5 or not row[0].startswith('BP_'):
            continue
        out[row[0]] = {
            'kind': row[1],
            'tier': int(row[2]) if row[2].isdigit() else 0,
            'random': row[3] == '1',
            'prerequisite': None if row[4] == 'None' else row[4],
        }
    return out


def parse_perk_level(text: str) -> dict[str, Any]:
    """One level of a perk in PerkData.csv. Its numbers are either 'cost:value' (the level is
    bought in one step) or 'share:cost:share:cost:...:value' (in steps, each a share of the
    way). Then come what buying the level opens: 'PERK=name' for another perk, and
    'COMPONENT=name' for a visual part of the ship."""
    numbers: list[float] = []
    perks: list[str] = []
    components: list[str] = []
    for token in text.split(':'):
        for part in token.split(';'):
            if part.startswith('PERK='):
                perks.append(part[5:])
            elif part.startswith('COMPONENT='):
                components.append(part[10:])
            elif part:
                numbers.append(float(part))
    if not numbers:
        raise ValueError('a perk level with no numbers: %r' % text)
    steps = numbers[:-1]
    costs = [int(c) for c in steps[1::2]] if len(steps) > 1 else [int(steps[0])] if steps else []
    return {'costs': costs, 'value': numbers[-1], 'unlocks': perks, 'components': components}


def parse_perks(text: str) -> list[dict[str, Any]]:
    """PerkData.csv, whose fields are separated by '|~', in the order of the file. The save
    keeps the perks in the same order."""
    out = []
    for line in text.splitlines():
        fields = line.split('|~')
        if len(fields) < 12:
            continue
        out.append(
            {
                'id': fields[1],
                'group': fields[0],
                'ship': int(fields[2]),  # -1 for all ships
                'name': fields[4],
                'description': fields[5],
                'icon': gameicons.texture_name(fields[6]),
                'base': fields[7],
                'format': fields[8],
                'decrease': fields[9] == 'Decrease',
                'hardcore': int(fields[10] or 0),  # the level in a hardcore run (ApplyHardcoreModePerks)
                'levels': [parse_perk_level(f) for f in fields[11:] if f.strip()],
            }
        )
    return out


_GLYPH = re.compile(
    r'IncompatibleShips = \{([^}]*)\};.*?AddGlyph\(\s*EGlyphID::(\w+),\s*EGlyphType::(\w+),\s*FName\("([^"]*)"\),'
    r'.*?NSLOCTEXT\("GLYPHS",\s*"[^"]*",\s*"((?:[^"\\]|\\.)*)"\),\s*(-?\d+),.*?'
    r'NSLOCTEXT\("GLYPHS",\s*"[^"]*",\s*"((?:[^"\\]|\\.)*)"\),\s*'
    r'NSLOCTEXT\("GLYPHS",\s*"[^"]*",\s*"((?:[^"\\]|\\.)*)"\)',
    re.DOTALL,
)
_GLYPH_ICON = re.compile(r'FString\("([^"]*)"\)')


def parse_glyphs(text: str) -> list[dict[str, Any]]:
    """GlyphData.inl, the C++ that adds each glyph. A glyph has a positive effect, and some
    also have a negative one. Some cannot be used on some ships."""
    out = []
    for block in text.split('\n}\n'):
        m = _GLYPH.search(block)
        if not m:
            continue
        ships, gid, kind, category, name, _, positive, negative = m.groups()
        icon = _GLYPH_ICON.search(block, m.end())
        out.append(
            {
                'id': 'EGlyphID::' + gid,
                'type': kind,
                'category': category.removesuffix(' Category'),
                'name': name,
                'positive': positive,
                'negative': negative,
                'incompatible_ships': [int(s) for s in ships.split(',') if s.strip()],
                'icon': gameicons.texture_name(icon.group(1)) if icon else None,
            }
        )
    return out


# ---- the blueprints


def category(values: dict[str, Any]) -> str:
    """The equipment category of a blueprint from its merged default values, or ''."""
    return _enum_value(values.get('EquipmentCategory')) or NATIVE_CATEGORIES.get(values.get('_native') or '', '')


def read_blueprints(
    game: str,
    folders: tuple[str, ...],
    progress: Callable[[str], object] | None = None,
    classes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """The default values of every blueprint in `folders` (paths below RSG/Content), with the
    values of their parent blueprints filled in. Keyed by class path. Each also has '_parent',
    the class name of its parent, and '_native', the name of the C++ class at the top of its
    parents. If `classes` is given, it gets an entry for each blueprint (see class_entry)."""
    files = {}
    for folder in folders:
        if progress:
            progress('Reading %s…' % folder)
        found = pak.read_files(game, CONTENT + folder, lambda rest: rest.endswith(('.uasset', '.uexp')))
        files.update({folder + rest: data for rest, data in found.items()})
    own: dict[str, dict[str, Any]] = {}
    by_class: dict[str, str] = {}
    for name, data in files.items():
        if not name.endswith('.uasset'):
            continue
        base = name[: -len('.uasset')]
        try:
            asset = uasset.Asset(data, files.get(base + '.uexp', b''))
            generated = asset.generated_class
            if generated is None:
                continue
            values = asset.defaults()
        except uasset.AssetError:
            continue
        path = class_path(base, generated['name'])
        if classes is not None:
            classes[path] = class_entry(asset, values)
        values['_parent'] = asset.parent
        own[path] = values
        by_class[path.rsplit('.', 1)[-1]] = path

    merged: dict[str, dict[str, Any]] = {}

    def resolve(path: str, seen: tuple[str, ...] = ()) -> dict[str, Any]:
        if path in merged:
            return merged[path]
        values = own[path]
        parent = by_class.get(values['_parent'] or '')
        if parent and parent not in seen:
            result = dict(resolve(parent, (*seen, path)))
        else:
            result = {'_native': values['_parent']}
        result.update(values)
        merged[path] = result
        return result

    for path in own:
        resolve(path)
    return merged


# values of a blueprint that attributes.py does not need, and that make the cache large
_NOT_NEEDED = ('UberGraphFrame', 'EquipmentDescription', 'EquipmentName', 'ResourceName')


# The starting loadouts. BP_GameInstanceBase lists the ship classes in PlayerShipClasses, in the
# order of SHIPS. AShipBase::GetLoadOut gives loadout A (0) from the items in the slots of the
# ship's components. It gives B (1) and C (2) from the ship's Loadouts array.
#
# The number of entries in each slot list of the components is the number of slots that the
# ship has without perks. UGameplayLib::InitPlayerShipWithPerkAndGlyphData adds the value of
# the ship's perk for the kind (for example GetPrimaryWeaponsSlotCountMod) to that number.
# Some ships have no perk for a kind: the Scout and the Sentinel have no perk for primary
# weapon slots, so they always have the default number.
GAME_INSTANCE = 'Blueprints/Framework/BP_GameInstanceBase'
LOADOUT_NAMES = ['A', 'B', 'C']
_LOADOUT_SLOTS = [  # component, slot list, the field with the amount (None: 1), kind
    ('WeaponComponent_0', 'PrimaryWeaponSlots', None, 'PrimaryWeapon'),
    ('WeaponComponent_0', 'SecondaryWeaponSlots', 'Ammo', 'SecondaryWeapon'),
    ('DeviceComponent_0', 'DeviceSlots', None, 'Device'),
    ('ConsumableComponent_0', 'ConsumableSlots', 'Amount', 'Consumable'),
]


def read_loadouts(
    game: str, progress: Callable[[str], object] | None = None
) -> tuple[list[list[list[dict[str, Any]]]], list[dict[str, int]]]:
    """The starting loadouts and the default slot counts of each ship, in the order of SHIPS.
    Each ship has loadouts A, B and C. Each loadout is a list of {'path': class path, 'amount':
    ammo or number}. For loadout A, GetLoadOut gives the Kickstarter Pulse Laser in place of
    the Pulse Laser to a pilot with that backer reward. This list does not show that. The
    slot counts are {kind: number of slots without perks}."""
    if progress:
        progress('Reading the ships…')
    files = pak.read_files(
        game,
        CONTENT + 'Blueprints/',
        lambda rest: (
            rest.startswith(('Ships/', GAME_INSTANCE[len('Blueprints/') :] + '.'))
            and rest.endswith(('.uasset', '.uexp'))
        ),
    )
    by_class: dict[str, tuple[str | None, dict[str, Any], dict[str, dict[str, Any]]]] = {}
    ship_classes: list[str] = []
    for name, data in files.items():
        if not name.endswith('.uasset'):
            continue
        base = name[: -len('.uasset')]
        try:
            asset = uasset.Asset(data, files.get(base + '.uexp', b''))
            generated = asset.generated_class
            if generated is None:
                continue
            defaults = asset.defaults()
            if 'Blueprints/' + base == GAME_INSTANCE:
                ship_classes = [str(p) for p in defaults.get('PlayerShipClasses') or []]
                continue
            by_class[str(generated['name'])] = (asset.parent, defaults, asset.components())
        except uasset.AssetError:
            continue

    def merged(cls: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        chain = []
        while cls in by_class and cls not in chain:
            chain.append(cls)
            cls = by_class[cls][0] or ''
        defaults: dict[str, Any] = {}
        parts: dict[str, dict[str, Any]] = {}
        for c in reversed(chain):
            _parent, values, components = by_class[c]
            defaults.update(values)
            for part, props in components.items():
                parts.setdefault(part, {}).update(props)
        return defaults, parts

    out = []
    slot_counts = []
    for path in ship_classes:
        defaults, parts = merged(path.rsplit('.', 1)[-1])
        first = []
        counts = {}
        for part, key, amount, kind in _LOADOUT_SLOTS:
            slots = parts.get(part, {}).get(key) or []
            counts[kind] = len(slots)
            for slot in slots:
                if slot.get('Class'):
                    first.append({'path': slot['Class'], 'amount': int(slot[amount]) if amount else 1})
        loadouts = [first]
        for entry in defaults.get('Loadouts') or []:
            items = next((v for k, v in entry.items() if k.startswith('Loadout')), None) or []
            loadouts.append(
                [{'path': i['PickupClass'], 'amount': int(i['Amount'])} for i in items if i.get('PickupClass')]
            )
        out.append(loadouts)
        slot_counts.append(counts)
    return out, slot_counts


def class_entry(asset: uasset.Asset, values: dict[str, Any]) -> dict[str, Any]:
    """What attributes.py needs of a blueprint. That is the class name of its parent, its
    own default values (not those of its parents), and the code of its functions."""
    return {
        'parent': asset.parent,
        'values': {k: v for k, v in values.items() if k not in _NOT_NEEDED},
        'functions': kismet.functions(asset),
    }


def parse_locres(data: bytes) -> dict[str, dict[str, str]]:
    """The texts of a .locres file (version 0 or 1), as {namespace: {key: text}}."""
    p = 0

    def string() -> str:
        nonlocal p
        (n,) = struct.unpack_from('<i', data, p)
        p += 4
        if n < 0:
            text = data[p : p - 2 * n].decode('utf-16-le')
            p -= 2 * n
        else:
            text = data[p : p + n].decode('latin-1')
            p += n
        return text.rstrip('\0')

    p = 16  # the magic GUID
    version = data[p]
    p += 1
    if version > 1:
        raise ValueError('a .locres of version %d' % version)
    (strings_at,) = struct.unpack_from('<q', data, p)
    p += 8
    keys_at = p
    p = strings_at
    (count,) = struct.unpack_from('<i', data, p)
    p += 4
    strings = [string() for _ in range(count)]
    p = keys_at
    out: dict[str, dict[str, str]] = {}
    (namespaces,) = struct.unpack_from('<I', data, p)
    p += 4
    for _ in range(namespaces):
        namespace = string()
        (keys,) = struct.unpack_from('<I', data, p)
        p += 4
        for _ in range(keys):
            key = string()
            p += 4  # the hash of the source string
            (index,) = struct.unpack_from('<i', data, p)
            p += 4
            out.setdefault(namespace, {})[key] = strings[index]
    return out


# the namespaces of the texts that the editor keeps
TEXT_NAMESPACES = ('GetShipClassName', 'EquipmentInfo')


def _kind_from_parents(path: str, blueprints: dict[str, dict[str, Any]], listed: dict[str, dict[str, Any]]) -> str:
    """The kind of an item that EquipmentData.csv does not list: that of the nearest parent it
    does list, or else a guess from the folder."""
    by_class = {p.rsplit('.', 1)[-1]: p for p in blueprints}
    seen = set()
    current: str | None = path
    while current and current not in seen:
        seen.add(current)
        name = short_name(current)
        if name in listed:
            return str(listed[name]['kind'])
        current = by_class.get(blueprints[current].get('_parent') or '')
    folder = path.split('/')[4] if path.count('/') > 4 else ''
    values = blueprints[path]
    if folder == 'Weapons':
        return 'SecondaryWeapon' if 'MaxAmmoPerSlot' in values else 'PrimaryWeapon'
    return {'Devices': 'Device', 'Consumables': 'Consumable', 'Mods': 'Mod', 'Buffs': 'Buff'}.get(folder, '')


class GameData:
    """The tables, and lookups in them that work when an entry is not there."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        self.equipment: dict[str, dict[str, Any]] = data.get('equipment', {})
        self.resources: dict[str, dict[str, Any]] = data.get('resources', {})
        self.perks: list[dict[str, Any]] = data.get('perks', [])
        self.glyphs: list[dict[str, Any]] = data.get('glyphs', [])
        self.source: dict[str, Any] = data.get('source', {})
        self.classes: dict[str, dict[str, Any]] = data.get('classes', {})
        self.texts: dict[str, dict[str, str]] = data.get('texts', {})
        self.loadouts: list[list[list[dict[str, Any]]]] = data.get('loadouts', [])
        self.slot_counts: list[dict[str, int]] = data.get('slot_counts', [])
        self.perk_by_id = {p['id']: p for p in self.perks}
        self.glyph_by_id = {g['id']: g for g in self.glyphs}

    def __bool__(self) -> bool:
        return bool(self.equipment)

    def to_json(self) -> dict[str, Any]:
        return {
            'format': FORMAT,
            'source': self.source,
            'equipment': self.equipment,
            'resources': self.resources,
            'perks': self.perks,
            'glyphs': self.glyphs,
            'classes': self.classes,
            'texts': self.texts,
            'loadouts': self.loadouts,
            'slot_counts': self.slot_counts,
        }

    # ---- lookups

    def name(self, path: str) -> str:
        """The name the game shows for an item or resource, or the blueprint name."""
        entry = self.equipment.get(path) or self.resources.get(path)
        return entry['name'] if entry and entry.get('name') else short_name(path)

    def icon(self, path: str) -> str | None:
        """The texture of the icon of an item or resource, a path below /Game/ such as
        'UI/HUD/Images/Equipment/equip_dev_energy_shield', or None."""
        entry = self.equipment.get(path) or self.resources.get(path)
        return entry.get('icon') if entry else None

    def icons(self) -> set[str]:
        """The textures of the icons of all items, resources, perks, glyphs and ships."""
        entries = (*self.equipment.values(), *self.resources.values(), *self.perks, *self.glyphs)
        return {e['icon'] for e in entries if e.get('icon')} | set(SHIP_ICONS)

    def kind(self, path: str) -> str:
        return str(self.equipment.get(path, {}).get('kind', ''))

    def items(self, kind: str, offered: bool = True) -> list[str]:
        """The class paths of the items of one kind, by name. With `offered`, only the items
        that the game lists in EquipmentData.csv and still gives, and the backer items."""
        out = [
            path
            for path, e in self.equipment.items()
            if e.get('kind') == kind
            and (not offered or (e.get('listed') and not e.get('removed')) or short_name(path) in BACKER_ITEMS)
        ]
        return sorted(out, key=lambda p: (self.name(p).lower(), p))

    def blueprints(self) -> list[str]:
        """The items that can be a blueprint in the hangar. These are the items in
        EquipmentData.csv, but not the buffs, the items the game no longer gives, and the
        legendary mod."""
        return [
            path
            for kind in KINDS
            if kind != 'Buff'
            for path in self.items(kind)
            if short_name(path) != 'BP_Mod_Weapon_Legendary' and short_name(path) not in BACKER_ITEMS
        ]

    def loadout(self, ship: int, index: int) -> list[dict[str, Any]] | None:
        """The items of a starting loadout of a ship (see read_loadouts), or None if the game
        data does not have it."""
        if 0 <= ship < len(self.loadouts) and 0 <= index < len(self.loadouts[ship]):
            return self.loadouts[ship][index]
        return None

    def default_slots(self, ship: int, kind: str) -> int | None:
        """The number of slots of a kind that a ship has without perks (see read_loadouts), or
        None if the game data does not have it."""
        if 0 <= ship < len(self.slot_counts):
            return self.slot_counts[ship].get(kind)
        return None

    def mods_for(self, path: str) -> list[str]:
        """The mods that fit an item, by the item's category."""
        category = self.equipment.get(path, {}).get('category')
        return [m for m in self.items('Mod') if category and category in self.equipment[m].get('compatible', [])]

    # ---- reading and building

    @classmethod
    def load(cls, path: str | None = None) -> GameData:
        """The tables from `path` (default: the cache file). Empty if there is no such file
        or it cannot be read."""
        path = path or cache_file()
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except OSError, ValueError:
            return cls()
        if not isinstance(data, dict) or data.get('format') != FORMAT:
            return cls()
        return cls(data)

    def save(self, path: str | None = None) -> str:
        path = path or cache_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + '.new', 'w', encoding='utf-8') as f:
            json.dump(self.to_json(), f, indent=1, sort_keys=True)
        os.replace(path + '.new', path)
        return path

    @classmethod
    def build(cls, game: str, progress: Callable[[str], object] | None = None) -> GameData:
        """Reads the tables from the game installed at `game`."""
        if progress:
            progress('Reading the data files…')
        data = pak.read_files(game, CONTENT + 'DataFiles/')
        listed = parse_equipment_csv(data['EquipmentData.csv'].decode('latin-1'))
        perks = parse_perks(data['PerkData.csv'].decode('latin-1'))
        glyphs = parse_glyphs(data['GlyphData.inl'].decode('latin-1'))
        classes: dict[str, dict[str, Any]] = {}
        blueprints = read_blueprints(game, ('Blueprints/Equipment/', 'Blueprints/Pickups/'), progress, classes)
        classes = {p: c for p, c in classes.items() if '/Equipment/' in p and '/Impacts/' not in p}
        texts = {}
        locres = pak.read_files(game, CONTENT + 'Localization/BaseGame_ShortTexts/en/')
        if locres:
            found = parse_locres(next(iter(locres.values())))
            texts = {ns: found[ns] for ns in TEXT_NAMESPACES if ns in found}

        equipment = {}
        resources = {}
        for path, values in blueprints.items():
            name = short_name(path)
            if 'ResourceName' in values and '/Pickups/' in path:
                resources[path] = {'name': _source(values['ResourceName'])}
                icon = values.get('ResourceIconFull') or values.get('ResourceIcon')
                if isinstance(icon, dict) and (texture := gameicons.texture_name(icon.get('ResourceObject'))):
                    resources[path]['icon'] = texture
                if any(values.get('MaxResourceAmount') or []):
                    resources[path]['max_amount'] = values['MaxResourceAmount']
                continue
            if '/Equipment/' not in path or 'EquipmentName' not in values or name.endswith('_Base'):
                continue
            row = listed.get(name, {})
            entry = {
                'name': _source(values.get('EquipmentName')),
                'description': _source(values.get('EquipmentDescription')),
                'kind': row.get('kind') or _kind_from_parents(path, blueprints, listed),
                'category': category(values),
                'tier': row.get('tier', 0),
                'listed': bool(row),
                'removed': bool(values.get('bRemovedEquipment')),
            }
            if texture := gameicons.texture_name(values.get('EquipmentIcon')):
                entry['icon'] = texture
            if 'MaxAmmoPerSlot' in values:
                entry['max_ammo'] = values['MaxAmmoPerSlot']
            if 'MaxAmountPerSlot' in values:
                entry['max_amount'] = values['MaxAmountPerSlot']
            if values.get('NanobotBonus'):
                entry['nanobot_bonus'] = values['NanobotBonus']
            if values.get('Duration'):
                entry['duration'] = values['Duration']
            if values.get('bOneTimeUseOnly'):
                entry['one_time'] = True
            if values.get('CompatibleEquipment'):
                entry['compatible'] = sorted({_enum_value(c) for c in values['CompatibleEquipment']})
            if row.get('prerequisite'):
                entry['prerequisite'] = row['prerequisite']
            if values.get('EquipmentAttributes'):
                entry['attributes'] = [_enum_value(a) for a in values['EquipmentAttributes']]
            if values.get('IncompatibleShips'):
                entry['incompatible_ships'] = [_enum_value(s) for s in values['IncompatibleShips']]
            equipment[path] = entry
        loadouts, slot_counts = read_loadouts(game, progress)
        source = {'game': game, 'paks': {os.path.basename(p): os.path.getsize(p) for p in pak.pak_files(game)}}
        return cls(
            {
                'equipment': equipment,
                'resources': resources,
                'perks': perks,
                'glyphs': glyphs,
                'classes': classes,
                'texts': texts,
                'loadouts': loadouts,
                'slot_counts': slot_counts,
                'source': source,
            }
        )

    def is_current(self, game: str) -> bool:
        """Whether the tables came from the game as it is now installed at `game`."""
        paks = {os.path.basename(p): os.path.getsize(p) for p in pak.pak_files(game)}
        return bool(self) and self.source.get('paks') == paks
