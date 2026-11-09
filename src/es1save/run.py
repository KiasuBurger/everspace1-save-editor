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

"""The run in progress: CurrentRunSave.sav, or CurrentHCRunSave.sav for a hardcore run (both
of class CurrentRunData).

    Credits, FuelAmount, PlayerHealthRatio      numbers
    Resources                                   PickupEntry: PickupClass, Amount, ...
    PrimaryWeapons, SecondaryWeapons            WeaponInfo: Class, Ammo, InstalledMods,
                                                InstalledModSeeds, bIgnoreInSelection
    Devices                                     DeviceInfo: Class, InstalledMods,
                                                InstalledModSeeds, bIgnoreInSelection
    Consumables                                 ConsumableInfo: Class, Amount,
                                                CurrentCoolDown, bIgnoreInSelection
    BonusGear                                   PickupEntry: the gear the run starts with
    ShipIndex, Difficulty, CurrentSystem, ...   where the run is

The game keeps one regular run and one hardcore run at the same time. A hardcore run has
bIsHardcoreRun, its own Perks, and Handicaps (see the hardcore runs below).

A run that has not started yet has bNeedsInitWithPawnDefaults set and holds little more
than BonusGear. The game gives the ship its equipment when the run starts.

The game keeps one entry for each device slot and each consumable slot. An empty slot is an
entry whose Class is None, and each item stays in its slot. ConsumablesIndex, the selected
consumable, is the number of a slot. In the saves that we examined, the weapon lists hold only
weapons. A weapon slot buff adds an empty entry to a weapon list (see the buffs below).

The game probably adds one seed to InstalledModSeeds for each mod that it installs. It does
not remove seeds: an empty slot can keep the seeds of the item that was in it. The editor adds
a seed when an item has more mods than seeds, and it does not remove the seeds of an item.

A primary weapon has an Ammo of 1. The Ancient Weapon, which the enhancement gives, has 0.
A secondary weapon that the pilot crafts gets 1 ammo.

Nothing here touches GTK, so it can be tested without a display.
"""

import random
from typing import Any, NamedTuple

from . import profile
from .gamedata import KINDS, GameData, short_name
from .profile import get, put
from .savegame import Properties

CLASS = 'CurrentRunData'
RESOURCES = 'Resources'
BONUS_GEAR = 'BonusGear'
NOT_STARTED = 'bNeedsInitWithPawnDefaults'
MODS = 'InstalledMods'
SEEDS = 'InstalledModSeeds'
KIND_NAMES = {
    'PrimaryWeapon': 'Primary weapon',
    'SecondaryWeapon': 'Secondary weapon',
    'Device': 'Device',
    'Consumable': 'Consumable',
    'Mod': 'Mod',
    'Buff': 'Buff',
}
MOD_LIMIT = 3  # mods on one item, which the Sentinel's Modifications perk makes 4
EMPTY = 'None'  # the Class of an empty slot
SEED_LIMIT = 1 << 23  # the seeds in the game's saves are less than this


class Slots:
    """One list of equipment in the run: its property, struct, and the perk that gives slots."""

    def __init__(self, kind: str, key: str, struct: str, perk: str, label: str, keeps_empty: bool) -> None:
        self.kind = kind
        self.key = key
        self.struct = struct
        self.perk = perk
        self.label = label
        self.keeps_empty = keeps_empty  # the game keeps an entry for each empty slot


SLOTS = [
    Slots('PrimaryWeapon', 'PrimaryWeapons', 'WeaponInfo', 'Primary Weapon Slots', 'Primary weapons', False),
    Slots('SecondaryWeapon', 'SecondaryWeapons', 'WeaponInfo', 'Secondary Weapon Slots', 'Secondary weapons', False),
    Slots('Device', 'Devices', 'DeviceInfo', 'Devices', 'Devices', True),
    Slots('Consumable', 'Consumables', 'ConsumableInfo', 'Consumables', 'Consumables', True),
]
SLOTS_BY_KIND = {s.kind: s for s in SLOTS}


def started(props: Properties) -> bool:
    return not get(props, NOT_STARTED, False)


class Position(NamedTuple):
    """Where the run is, from 1."""

    sector: int
    location: int  # the column of the location in the map of its sector
    columns: int  # the number of columns in the map of the sector


def position(props: Properties) -> Position | None:
    """The sector and the location of the run. None if the map does not have the system or the
    location.

    CurrentSystem is a SystemID and CurrentLocation is a LocationID of WorldMap. Location IDs
    count across all the systems. The Sector of a system is its place in the run, and the Sector
    of a location is its column in its system, from 0. A system can have more than one location
    in a column. A path through the system visits one location in each column, and some links
    skip a column. The game wrote CurrentSystem 1 and CurrentLocation 7 for a run in sector 2, at
    the second column of the map. The game does not write a value of 0, so a missing value is 0."""
    world = get(props, 'WorldMap', {})
    systems = world.get('Systems', {}).get('value', [])
    system_id = int(get(props, 'CurrentSystem', 0))
    location_id = int(get(props, 'CurrentLocation', 0))
    system = next((s for s in systems if s['SystemID']['value'] == system_id), None)
    if system is None:
        return None
    locations = system['Locations']['value']
    location = next((loc for loc in locations if loc['LocationID']['value'] == location_id), None)
    if location is None:
        return None
    columns = max(int(loc['Sector']['value']) for loc in locations) + 1
    return Position(int(system['Sector']['value']) + 1, int(location['Sector']['value']) + 1, columns)


def ship(props: Properties) -> int:
    return int(get(props, 'ShipIndex', 0))


def is_empty(entry: Properties) -> bool:
    return bool(entry['Class']['value'] == EMPTY)


def items(props: Properties, slots: Slots) -> list[Properties]:
    """The items of a kind, without the empty slots."""
    return [e for e in get(props, slots.key, []) if not is_empty(e)]


def _list(props: Properties, slots: Slots) -> list[Properties]:
    entry = props.setdefault(slots.key, {'type': 'ArrayProperty<StructProperty<%s>>' % slots.struct, 'value': []})
    value: list[Properties] = entry['value']
    return value


def new_item(slots: Slots, path: str, amount: int = 1) -> Properties:
    """A new entry for an item, with the fields the game writes for its kind. `amount` is the
    ammo of a secondary weapon, or how many of a consumable."""
    entry: Properties = {'Class': {'type': 'ObjectProperty', 'value': path}}
    if slots.struct == 'WeaponInfo':
        entry['Ammo'] = {'type': 'IntProperty', 'value': amount if slots.kind == 'SecondaryWeapon' else 1}
    if slots.struct in ('WeaponInfo', 'DeviceInfo'):
        entry[MODS] = {'type': 'ArrayProperty<ObjectProperty>', 'value': []}
        entry[SEEDS] = {'type': 'ArrayProperty<IntProperty>', 'value': []}
    if slots.struct == 'ConsumableInfo':
        entry['Amount'] = {'type': 'IntProperty', 'value': amount}
        entry['CurrentCoolDown'] = {'type': 'FloatProperty', 'value': 0.0}
    entry['bIgnoreInSelection'] = {'type': 'BoolProperty', 'value': False}
    return entry


def add_item(props: Properties, slots: Slots, path: str, amount: int = 1) -> Properties:
    """Puts an item into the first empty slot, or adds an entry when no slot is empty."""
    entry = new_item(slots, path, amount)
    entries = _list(props, slots)
    empty = next((e for e in entries if is_empty(e)), None)
    if empty is None:
        entries.append(entry)
        return entry
    empty.clear()
    empty.update(entry)
    return empty


def put_item(props: Properties, slots: Slots, index: int, path: str, amount: int = 1) -> Properties:
    """Puts an item into slot `index`. An empty entry at that slot takes the item. Past the end
    of the list, devices and consumables get empty entries up to the slot, as the game writes
    them. A weapon goes at the end of its list, because weapon lists usually have no empty
    entries.
    Raises ValueError if the slot is not empty."""
    entries = _list(props, slots)
    entry = new_item(slots, path, amount)
    if index < len(entries):
        if not is_empty(entries[index]):
            raise ValueError('slot %d of the %s is not empty' % (index, slots.label.lower()))
        entries[index].clear()
        entries[index].update(entry)
        return entries[index]
    if slots.keeps_empty:
        while len(entries) < index:
            entries.append(new_item(slots, EMPTY, 0))
    entries.append(entry)
    return entry


def slot_count(props: Properties, slots: Slots, limit: int | None) -> int:
    """The number of slots to show for a kind: the limit from the perks, or more if the list
    has more entries. When the limit is not known, there is one empty slot to add to."""
    entries = get(props, slots.key, [])
    if limit is None:
        return len(entries) + (0 if any(is_empty(e) for e in entries) else 1)
    return max(len(entries), limit)


def remove_item(props: Properties, slots: Slots, entry: Properties) -> None:
    """Removes an item. For devices and consumables, the slot stays as an empty entry, so that
    the other items keep their slots."""
    entries = _list(props, slots)
    index = next(i for i, e in enumerate(entries) if e is entry)
    if slots.keeps_empty:
        entry.clear()
        entry.update(new_item(slots, EMPTY, 0))
    else:
        del entries[index]


def replace_item(entry: Properties, path: str, game: GameData) -> None:
    """Changes what an item is. Its mods stay only if they fit the new item."""
    entry['Class']['value'] = path
    if MODS in entry:
        fits = set(game.mods_for(path))
        entry[MODS]['value'] = [m for m in entry[MODS]['value'] if m in fits]


def amount_key(slots: Slots) -> str | None:
    """The field that holds how many of an item there are, or None for an item without one."""
    return {'SecondaryWeapon': 'Ammo', 'Consumable': 'Amount'}.get(slots.kind)


def default_amount(game: GameData, path: str) -> int:
    """How many of an item one slot holds, from the item's blueprint: 1 if it does not say."""
    entry = game.equipment.get(path, {})
    return int(entry.get('max_ammo') or entry.get('max_amount') or 1)


def slot_limit(player: Properties | None, game: GameData, slots: Slots, ship_index: int) -> int | None:
    """How many items of a kind the ship carries, from the pilot's perks. The base value of
    each such perk is the number of slots that the ship has without perks. A ship that has no
    perk for the kind always has that number (see gamedata.read_loadouts): the Sentinel has
    1 primary weapon slot. None when the pilot's save is not open, or the game data does not
    have the number."""
    if player is None:
        return None
    value = profile.perk_value(player, game, profile.ship_perk(slots.perk, ship_index))
    if value is None:
        return game.default_slots(ship_index, slots.kind)
    return int(value)


def mod_limit(player: Properties | None, game: GameData, slots: Slots, ship_index: int) -> int:
    """How many mods an item takes. The Sentinel's Modifications perk adds one to devices at
    level 1, and one to primary weapons at level 2."""
    level = 0
    if player is not None and ship_index == 3:
        perk = next((p for p in profile.perks(player, game) if p.id == 'Modifications Tech Fighter'), None)
        level = perk.level if perk else 0
    if slots.kind == 'Device' and level >= 1 or slots.kind == 'PrimaryWeapon' and level >= 2:
        return MOD_LIMIT + 1
    return MOD_LIMIT


def mods(entry: Properties) -> list[str]:
    return list(entry[MODS]['value']) if MODS in entry else []


def add_mod(entry: Properties, path: str) -> None:
    """Installs a mod, and adds a random seed when the item has fewer seeds than mods."""
    entry[MODS]['value'].append(path)
    seeds = entry[SEEDS]['value']
    while len(seeds) < len(entry[MODS]['value']):
        seeds.append(random.randrange(1, SEED_LIMIT))


def remove_mod(entry: Properties, index: int) -> None:
    del entry[MODS]['value'][index]


def run_resources(game: GameData) -> list[str]:
    """The resources a run can hold, by name. The Viridian Energy stays with the pilot."""
    return sorted((p for p in game.resources if 'OkkarEnergy' not in p), key=lambda p: game.name(p).lower())


# The groups of resources, in the order of the resource bar of the game. The game gives each
# of the first two groups its own icon colour (menu_res_a_* and menu_res_n_*). The names
# are the end of the blueprint name: BP_PickupResourceScrap.
RESOURCE_GROUPS = (
    ('Scrap', 'Gel', 'Compound', 'PowerCell', 'Processor'),
    ('Crystal', 'Gas', 'Ore', 'Plasma', 'DarkMatter', 'DarkEnergy'),
    ('NanoBots', 'Keycodes'),
)


def resource_rows(amounts: list[tuple[str, int]]) -> list[list[tuple[str, int]]]:
    """The resources and their amounts in the groups of RESOURCE_GROUPS, in the order of the game.
    A resource that is not in a group goes in a last row. The list has no empty rows."""
    order = {name: (row, n) for row, names in enumerate(RESOURCE_GROUPS) for n, name in enumerate(names)}
    last = (len(RESOURCE_GROUPS), 0)
    rows: list[list[tuple[str, int]]] = [[] for _ in range(len(RESOURCE_GROUPS) + 1)]

    def place(path: str) -> tuple[int, int]:
        return order.get(short_name(path).removeprefix('BP_PickupResource'), last)

    for path, amount in sorted(amounts, key=lambda pa: place(pa[0])):
        rows[place(path)[0]].append((path, amount))
    return [row for row in rows if row]


NANOBOTS = 'BP_PickupResourceNanoBots'


def resource_limit(props: Properties, game: GameData, path: str) -> int | None:
    """The amount of a resource that the ship of the run can hold, or None if the resource has
    no limit.

    GetMaxResourceAmount adds two values. The first is MaxResourceAmount of the resource's
    blueprint, which has one value for each ship (ShipIndex). The second is the value for the
    resource in MaxResourceBonus of the game mode. The Nanobot Canister buff puts NanobotBonus
    there for the nano bots when the game installs it. The game installs each buff in Buffs
    when it loads the run. Map_Add replaces the value, so two canisters give the bonus of one.
    A limit of 0 means no limit to the pickups. The game does not lower an amount that is more
    than the limit. It stops the ship from collecting more nano bots, but a damaged hull can
    make an exception (CanBeCollected)."""
    limits = game.resources.get(path, {}).get('max_amount') or []
    index = ship(props)
    if not 0 <= index < len(limits) or not limits[index]:
        return None
    bonus = 0
    if short_name(path) == NANOBOTS:
        buffs = [e['Class']['value'] for e in get(props, 'Buffs', []) if 'Class' in e]
        bonus = max((int(game.equipment.get(b, {}).get('nanobot_bonus', 0)) for b in buffs), default=0)
    return int(limits[index]) + bonus


def resources(props: Properties, game: GameData) -> list[tuple[str, int]]:
    """Every resource of the game with the amount the run has of it, by name."""
    have = {e['PickupClass']['value']: int(e['Amount']['value']) for e in get(props, RESOURCES, [])}
    paths = set(have) | set(run_resources(game))
    return sorted(((p, have.get(p, 0)) for p in paths), key=lambda pa: game.name(pa[0]).lower())


# ---- the buffs
#
# The tuning station sells buffs ("ship upgrades"). Buffs is a list of BuffInfo: Class,
# CurrentDuration and bInstalled. UBuffComponent::InstallBuff adds an entry with the
# Duration of the buff's blueprint and bInstalled false, and SpawnBuff installs it (OnInstall)
# and sets bInstalled. TickComponent lowers CurrentDuration to 0. A buff with a Duration
# ("Lifetime: 00:10:00" in the game) goes away at 0. A buff without one has a CurrentDuration
# of 0 and stays for the run. When the game loads the run, it installs each buff again, but not
# a buff that has bOneTimeUseOnly and bInstalled. BuffCanBeInstalled lets a ship have more than
# one buff of a kind, because no buff clears bAllowOtherBuffsOfSameCategory.
#
# The slot buffs have bOneTimeUseOnly. OnInstall adds an empty entry to the list of the run
# (Devices, for example), and the game makes one slot for each entry of the list when it loads
# the run. An installed slot buff is the reason for one slot more than the perks give. When
# the editor adds a slot buff, bInstalled is false, so the game adds the slot when it loads the
# run. When the editor removes an installed slot buff, the slot stays.

BUFFS = 'Buffs'
SLOT_BUFFS = {
    'BP_Buff_PrimaryWeaponSlot': 'PrimaryWeapon',
    'BP_Buff_SecondaryWeaponSlot': 'SecondaryWeapon',
    'BP_Buff_DeviceSlot': 'Device',
    'BP_Buff_ConsumableSlot': 'Consumable',
}


def buffs(props: Properties) -> list[Properties]:
    value: list[Properties] = get(props, BUFFS, [])
    return value


def buff_installed(entry: Properties) -> bool:
    return bool(entry.get('bInstalled', {}).get('value', False))


def add_buff(props: Properties, game: GameData, path: str) -> Properties:
    """Adds a buff as InstallBuff does. The game installs it when it loads the run."""
    entry: Properties = {
        'Class': {'type': 'ObjectProperty', 'value': path},
        'CurrentDuration': {'type': 'FloatProperty', 'value': float(game.equipment.get(path, {}).get('duration', 0))},
        'bInstalled': {'type': 'BoolProperty', 'value': False},
    }
    props.setdefault(BUFFS, {'type': 'ArrayProperty<StructProperty<BuffInfo>>', 'value': []})['value'].append(entry)
    return entry


def remove_buff(props: Properties, entry: Properties) -> None:
    entries = buffs(props)
    del entries[next(i for i, e in enumerate(entries) if e is entry)]


def set_buff_time(entry: Properties, seconds: float) -> None:
    """Sets the time that a buff with a Duration has left."""
    put(entry, 'CurrentDuration', float(seconds), 'FloatProperty')


def buff_slots(props: Properties, slots: Slots) -> int:
    """The number of slots of a kind that installed slot buffs added to the ship."""
    return sum(
        1 for e in buffs(props) if buff_installed(e) and SLOT_BUFFS.get(short_name(e['Class']['value'])) == slots.kind
    )


# ---- hardcore runs
#
# StartNewRun sets bIsHardcoreRun, and WriteSaveGame then writes the run to the hardcore slot
# (CurrentHCRunSave). A hardcore run keeps its own Perks, in the format of the pilot's Perks.
# ApplyHardcoreModePerks sets each perk to the level in field 11 of PerkData.csv. The game
# then reads the slot counts and the perk values from these perks, not from the pilot's. In
# the save that we examined, the run's lists had the slot counts of the run's perks.
#
# Handicaps is a list of glyph IDs of type HANDICAP. GetRandomHandicapOffers offers 2
# handicaps that are not in the list. In a hardcore run, IsGlyphEquipped does not look at the
# glyphs of the pilot's ship. In systems 0 to 5 it compares the glyph with the first entry of
# Handicaps only, and after system 5 it returns false. Thus the first entry is the active
# handicap, and the other entries are a record of the earlier handicaps. When the pilot
# chooses a handicap, WG_Handicap_Selection inserts it at index 0. The stats screen
# (WG_Stats_Handicaps) shows all the entries. The game writes Handicaps after the run gets
# its first handicap, as the last property of the run. A save with one handicap (2026-11-07)
# has the type and the bytes that add_handicap writes. In the save of 2026-11-08, the list
# changed from [NO_CONSUMABLES] to [RETRO, MAP, NO_CONSUMABLES].

HARDCORE = 'bIsHardcoreRun'
PERKS = 'Perks'
HANDICAPS = 'Handicaps'
PERK_CREDITS = 'CreditsSpentOnPerksDuringRun'
LAST_HANDICAP_SYSTEM = 5  # after this system, no handicap is active
HANDICAP_TYPE = 'ArrayProperty<EnumProperty>'


def hardcore(props: Properties) -> bool:
    return bool(get(props, HARDCORE, False))


def perk_props(props: Properties | None, player: Properties | None) -> Properties | None:
    """The tree whose Perks give the run its limits: the run's own for a hardcore run, else the
    pilot's. None when that tree is not open, or a hardcore run has no Perks."""
    if props is not None and hardcore(props):
        return props if PERKS in props else None
    return player


def handicaps(props: Properties) -> list[str]:
    return [str(g) for g in get(props, HANDICAPS, [])]


def handicap_choices(props: Properties, game: GameData) -> list[str]:
    """The handicaps of the game that the run does not have, in the order of GlyphData.inl."""
    have = set(handicaps(props))
    return [g['id'] for g in game.glyphs if g.get('type') == 'HANDICAP' and g['id'] not in have]


def active_handicap(props: Properties) -> str | None:
    """The handicap that the game applies: the first entry of Handicaps. None when the run has
    no handicap, or is past system LAST_HANDICAP_SYSTEM."""
    chosen = handicaps(props)
    if not chosen or int(get(props, 'CurrentSystem', 0)) > LAST_HANDICAP_SYSTEM:
        return None
    return chosen[0]


def add_handicap(props: Properties, glyph: str) -> None:
    """Inserts a handicap at index 0, as the game does. The new handicap becomes the active
    one."""
    props.setdefault(HANDICAPS, {'type': HANDICAP_TYPE, 'value': []})['value'].insert(0, glyph)


def remove_handicap(props: Properties, index: int) -> None:
    del props[HANDICAPS]['value'][index]


# ---- the bonus gear
#
# The hangar makes BonusGear when the pilot starts a run (WG_HangarMenu): the offer that the
# pilot chose on the Bonus Gear screen, then random resources (GetRandomResourcesOfValue, for a
# value that the Bonus resources perk sets). GetRandomBonusGearOffers makes 2 offers (3 from
# level 5 of the Bonus gear perk). An offer has 1 entry below level 3, and 2 from level 3. An
# entry is a weapon, a device, a consumable or a resource (Keycodes or Nanobots, for example).
# The editor shows the items as GEAR_SLOTS slots, and the resources as one amount for each.

GEAR_SLOTS = 2
BONUS_GEAR_PERK = 'Bonus gear'


def bonus_item_choices(game: GameData) -> list[str]:
    """The weapons, devices and consumables that the editor offers as bonus gear."""
    return [p for kind in KINDS if kind not in ('Buff', 'Mod') for p in game.items(kind)]


def bonus_items(props: Properties, game: GameData) -> list[Properties]:
    """The entries of the bonus gear that are not resources, in their order."""
    return [e for e in get(props, BONUS_GEAR, []) if e['PickupClass']['value'] not in game.resources]


def bonus_resources(props: Properties, game: GameData) -> list[tuple[str, int]]:
    """Every resource of a run with the amount the bonus gear has of it, by name."""
    have: dict[str, int] = {}
    for entry in get(props, BONUS_GEAR, []):
        path = entry['PickupClass']['value']
        if path in game.resources:
            have[path] = have.get(path, 0) + int(entry['Amount']['value'])
    paths = set(have) | set(run_resources(game))
    return sorted(((p, have.get(p, 0)) for p in paths), key=lambda pa: game.name(pa[0]).lower())


def bonus_item_limit(player: Properties | None, game: GameData) -> int | None:
    """How many entries the offer has at the pilot's level of the Bonus gear perk: 0, 1 or 2.
    None when the pilot's save is not open, or the game has no such perk."""
    if player is None:
        return None
    level = profile.perk_value(player, game, BONUS_GEAR_PERK)
    if level is None:
        return None
    return 0 if level < 1 else 1 if level < 3 else 2


def _bonus_list(props: Properties) -> list[Properties]:
    entries: list[Properties] = props.setdefault(
        BONUS_GEAR, {'type': 'ArrayProperty<StructProperty<PickupEntry>>', 'value': []}
    )['value']
    return entries


def put_bonus_item(props: Properties, game: GameData, index: int, path: str, amount: int) -> None:
    """Puts an item in slot `index` of the bonus gear. A new item goes after the other items and
    before the resources, as the game puts the offer first."""
    entries = _bonus_list(props)
    items = bonus_items(props, game)
    if index < len(items):
        old = items[index]
        old['PickupClass']['value'] = path
        old['Amount']['value'] = amount
        return
    where = next((n for n, e in enumerate(entries) if e['PickupClass']['value'] in game.resources), len(entries))
    entries.insert(where, profile.pickup_entry(path, amount))


def remove_bonus_entry(props: Properties, entry: Properties) -> None:
    entries = _bonus_list(props)
    entries[:] = [e for e in entries if e is not entry]


def set_bonus_resource(props: Properties, path: str, amount: int) -> None:
    """Sets the amount of a resource in the bonus gear. An amount of 0 removes its entries."""
    entries = _bonus_list(props)
    kept = [e for e in entries if e['PickupClass']['value'] != path]
    if amount <= 0:
        entries[:] = kept
    elif len(kept) == len(entries):
        entries.append(profile.pickup_entry(path, amount))
    else:
        first = next(e for e in entries if e['PickupClass']['value'] == path)
        first['Amount']['value'] = amount
        entries[:] = [e for e in entries if e is first or e['PickupClass']['value'] != path]


def kind_name(game: GameData, path: str) -> str:
    """The kind of an item or resource, as the editor shows it, or '' when it is not known."""
    if path in game.resources:
        return 'Resource'
    return KIND_NAMES.get(game.kind(path), '')


def set_resource(props: Properties, path: str, amount: int) -> None:
    profile.set_pickup_amount(props, RESOURCES, path, amount)


def set_value(props: Properties, key: str, value: Any) -> None:
    put(props, key, value, 'FloatProperty' if isinstance(value, float) else 'IntProperty')
