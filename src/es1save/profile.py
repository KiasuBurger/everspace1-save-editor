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

"""The pilot's progress: CurrentPlayerSave.sav (class CurrentPlayerData).

    Perks                 one PerkInfo for each perk of PerkData.csv, in the same order:
                          Name, IsLocked, Level (whole levels bought), SubLevel (steps
                          bought towards the next level)
    UnlockedBlueprints    the class paths of the items the hangar can give as blueprints
    ShipsUnlocked         one bool for each ship (see gamedata.SHIPS)
    Glyphs                one GlyphState for each glyph of GlyphData.inl, in the same order:
                          ID, bUnlocked, bDecyphered (the game does not use
                          bDecyphered)
    ShipEquipment         one ShipEquipmentData for each ship: Glyphs (the enhancement
                          slots), SelectedLoadout, UnlockedLoadout (the starting loadouts,
                          see below), ShipColors
    PersistentResources   resources the pilot keeps between runs (Viridian energy)
    DNAFragments, NumRuns, NumWins, ...   numbers

Nothing here touches GTK, so it can be tested without a display.
"""

from typing import Any

from .gamedata import GameData
from .savegame import Properties

CLASS = 'CurrentPlayerData'
PERKS = 'Perks'
BLUEPRINTS = 'UnlockedBlueprints'
SHIPS = 'ShipsUnlocked'
GLYPHS = 'Glyphs'
SHIP_EQUIPMENT = 'ShipEquipment'
NO_GLYPH = 'EGlyphID::NONE'
ENHANCEMENT_SLOTS = 3
ENHANCEMENT_PERK = 'Enhancement Slots'
PERSISTENT = 'PersistentResources'
SHIP_SUFFIX = ['', ' Scout', ' Gunship', ' Tech Fighter']  # of a perk that is for one ship only


def get(props: Properties, key: str, default: Any = None) -> Any:
    entry = props.get(key)
    return entry['value'] if entry else default


def put(props: Properties, key: str, value: Any, kind: str = 'IntProperty') -> None:
    """Sets a value, and adds the property with type `kind` if the save does not have it."""
    if key in props:
        props[key]['value'] = value
    else:
        props[key] = {'type': kind, 'value': value}


# ---- perks


class Perk:
    """One perk of the save, with its definition from the game when there is one."""

    def __init__(self, entry: Properties, definition: dict[str, Any] | None) -> None:
        self.entry = entry
        self.definition = definition or {}

    @property
    def id(self) -> str:
        return str(self.entry['Name']['value'])

    @property
    def name(self) -> str:
        return str(self.definition.get('name') or self.id)

    @property
    def ship(self) -> int:
        """The ship the perk is for, or -1 for a perk of all ships."""
        return int(self.definition.get('ship', -1))

    @property
    def levels(self) -> list[dict[str, Any]]:
        return list(self.definition.get('levels', []))

    @property
    def level(self) -> int:
        return int(self.entry['Level']['value'])

    @property
    def sublevel(self) -> int:
        return int(self.entry['SubLevel']['value'])

    @property
    def locked(self) -> bool:
        return bool(self.entry['IsLocked']['value'])

    @property
    def hardcore(self) -> int:
        """The level that a hardcore run starts with: field 11 of PerkData.csv, no more than
        the last level."""
        return min(int(self.definition.get('hardcore', 0)), len(self.levels))

    @property
    def steps(self) -> int:
        """How many steps the next level is bought in: 0 when the perk is at its last level."""
        return len(self.levels[self.level]['costs']) if self.level < len(self.levels) else 0

    def value(self, level: int | None = None) -> float | None:
        """What the perk gives at a level (default: its own): the base value and the value of
        the level. None if the base is not a number."""
        level = self.level if level is None else level
        try:
            base = float(self.definition.get('base', ''))
        except ValueError:
            return None
        if level <= 0 or not self.levels:
            return base
        change = float(self.levels[min(level, len(self.levels)) - 1]['value'])
        return base - change if self.definition.get('decrease') else base + change

    def benefit(self, level: int | None = None) -> list[str]:
        """What the perk gives at a level (default: its own), as the hangar tells it: one line
        for each feature that the levels give, or the value in the unit of the perk."""
        value = self.value(level)
        if value is None:
            return [str(self.definition.get('base', ''))]
        texts = LEVEL_TEXTS.get(self.id)
        if texts is not None:
            if self.id in REPLACING_TEXTS:
                return texts[int(value) - 1 : int(value)] or ['Not available.']
            return texts[: int(value)] or ['Not available.']
        return [format_value(str(self.definition.get('format', '')), value)]


# The texts of each level of some perks, from UPerkCollection::InitPerkLevelDescriptions in the
# game's executable. GetPerkLevelText shows the text of the level, and makes a list of the texts
# of that level and the levels before it. Each level of Bonus resources replaces the level
# before it, so the editor shows only the text of the level for it.
REPLACING_TEXTS = {'Bonus resources'}
LEVEL_TEXTS = {
    'Retrieval': [
        "Reveals the location of your last clone's ship wreck on the map and lets you salvage it for resources.",
        'Adds chance to retrieve primary and secondary weapons.',
        'Adds chance to retrieve fuel.',
        'Adds chance to retrieve devices and consumables.',
        'Increases chances of retrieving anything.',
        'Retrieve at least one piece of equipment of each category (primary, secondary, devices, consumables).',
    ],
    'Bonus gear': [
        'Lets you choose additional random equipment before each run.',
        'Increases the quality of the bonus equipment.',
        'Adds a second item to each offer.',
        'Increases the quality of the bonus equipment.',
        'Adds a third offer.',
        'Lets you roll the dice once to get new random offers.',
    ],
    'Sector scanner': [
        'Shows threat levels on the map.',
        'Shows natural hazards on the map.',
        'Shows trader on the map.',
        'Shows service stations on the map.',
    ],
    'Bonus resources': [
        'Adds resources worth $ 500 to your ship.',
        'Adds resources worth $ 1000 to your ship.',
        'Adds resources worth $ 1500 to your ship.',
        'Adds resources worth $ 2000 to your ship.',
    ],
    'Trading': [
        'Service stations offer two services.',
        'Traders and service stations occasionally buy resources.',
        'Service stations offer three services.',
        'Increases fuel and repair capacity of service stations.',
        'Service stations and traders have more offers.',
    ],
    'Diplomacy': [
        'Reduce the chance of G&B units reporting your attacks.',
        'Further reduce the chance of G&B units reporting your attacks.',
        'G&B fighters will occasionally jump in to aid you in fighting outlaws.',
        'G&B fighters will more often jump in to aid you in fighting outlaws.',
    ],
    'Drones Gunship': [
        'Increases drone limit from 1 to 2.',
        'Deployed drones will come equipped with adaptive armor.',
        'Increases drone limit from 2 to 3.',
        'Deployed drones will come equipped with adaptive armor and shields.',
        'Deployed drones will regenerate 10% hull hitpoints after jumping.',
    ],
    'Modifications Tech Fighter': [
        'Increases the maximum amount of modifications for devices from 3 to 4.',
        'Increases the maximum amount of modifications for primary weapons from 3 to 4.',
    ],
}


def _number(value: float) -> str:
    """A number with at most 2 decimals and no zeros at the end."""
    return ('%.2f' % value).rstrip('0').rstrip('.')


def format_value(fmt: str, value: float) -> str:
    """A perk value in the unit of its format (the format column of PerkData.csv), as
    UPerkCollection::FormatValue writes it. The game uses 100 Unreal units for one metre."""
    match fmt.replace(' ', ''):
        case 'Percent':
            return _number(value * 100) + '%'
        case 'UnrealUnits':
            return _number(value / 100000) + 'km'
        case 'Level':
            return 'Level %d' % int(value)
        case 'IntValue':
            return '%d' % int(value)
        case 'Seconds':
            return _number(value) + 's'
        case 'Factor':
            return _number(value) + 'x'
        case 'Speed':
            return '%dm/s' % int(value / 100)
        case 'FloatPerSecond':
            return _number(value) + '/s'
    return _number(value)


def perks(props: Properties, game: GameData) -> list[Perk]:
    return [Perk(e, game.perk_by_id.get(e['Name']['value'])) for e in get(props, PERKS, [])]


def set_perk_level(props: Properties, game: GameData, perk: Perk, level: int) -> None:
    """Sets the whole levels of a perk and clears the steps towards the next. The perk is
    then unlocked, and so is each perk that its levels up to `level` open, as buying them
    in the hangar would do. A lower level locks nothing again."""
    level = max(0, min(level, len(perk.levels))) if perk.levels else max(0, level)
    perk.entry['Level']['value'] = level
    perk.entry['SubLevel']['value'] = 0
    if level:
        perk.entry['IsLocked']['value'] = False
    opened = {name for lv in perk.levels[:level] for name in lv['unlocks']}
    for other in perks(props, game):
        if other.id in opened:
            other.entry['IsLocked']['value'] = False


def set_perk_sublevel(perk: Perk, steps: int) -> None:
    perk.entry['SubLevel']['value'] = max(0, min(steps, max(perk.steps - 1, 0)))


def set_perk_locked(perk: Perk, locked: bool) -> None:
    perk.entry['IsLocked']['value'] = locked


def max_all_perks(props: Properties, game: GameData) -> int:
    """Unlocks every perk and buys every level. Returns how many perks changed."""
    changed = 0
    for perk in perks(props, game):
        before = (perk.level, perk.sublevel, perk.locked)
        if perk.levels:
            set_perk_level(props, game, perk, len(perk.levels))
        perk.entry['IsLocked']['value'] = False
        changed += before != (perk.level, perk.sublevel, perk.locked)
    return changed


def set_hardcore_levels(props: Properties, game: GameData) -> int:
    """Sets each perk to the level that a hardcore run starts with, as
    UPerkCollection::ApplyHardcoreModePerks does: it unlocks the perk and clears the steps
    towards the next level. Returns how many perks changed."""
    changed = 0
    for perk in perks(props, game):
        if not perk.definition:
            continue
        before = (perk.level, perk.sublevel, perk.locked)
        perk.entry['Level']['value'] = perk.hardcore
        perk.entry['SubLevel']['value'] = 0
        perk.entry['IsLocked']['value'] = False
        changed += before != (perk.level, perk.sublevel, perk.locked)
    return changed


def perk_value(props: Properties, game: GameData, perk_id: str) -> float | None:
    """The total a perk gives at its level in the save: the base value and the value of the
    level. None if the game or the save does not have the perk, or its base is not a number."""
    perk = next((p for p in perks(props, game) if p.id == perk_id), None)
    if perk is None or not perk.definition:
        return None
    return perk.value()


# ---- blueprints, ships and glyphs


def blueprints(props: Properties) -> list[str]:
    return list(get(props, BLUEPRINTS, []))


def set_blueprint(props: Properties, path: str, unlocked: bool) -> None:
    current = props.setdefault(BLUEPRINTS, {'type': 'ArrayProperty<ObjectProperty>', 'value': []})['value']
    if unlocked and path not in current:
        current.append(path)
    elif not unlocked and path in current:
        current.remove(path)


def ships(props: Properties) -> list[bool]:
    return [bool(v) for v in get(props, SHIPS, [])]


def set_ship(props: Properties, index: int, unlocked: bool) -> None:
    values = props[SHIPS]['value']
    if not 0 <= index < len(values):
        raise IndexError('the save has %d ships' % len(values))
    values[index] = unlocked


def glyphs(props: Properties) -> list[Properties]:
    return list(get(props, GLYPHS, []))


def set_glyph(entry: Properties, unlocked: bool) -> None:
    """Locks or unlocks a glyph. The editor does not change bDecyphered, because the game does
    not use it (see FORMAT.md)."""
    entry['bUnlocked']['value'] = unlocked


# ---- the enhancements of each ship
#
# ShipEquipment has one ShipEquipmentData for each ship. Its Glyphs array is the list of
# enhancement slots. Glyphs, sub-routines and handicaps all use these slots. The C++ constructor
# FShipEquipmentData() makes 3 entries of NONE, and NONE is an empty slot. EquipGlyph writes
# into the first NONE entry, and IsGlyphEquipped looks at all the entries. The perk
# 'Enhancement Slots' (with the suffix of the ship) sets how many slots the game lets the pilot
# fill (UPerkCollection::GetEnhancementSlotsCount).


def enhancements(props: Properties, ship: int) -> list[str]:
    """The glyph IDs in the enhancement slots of a ship, with NONE for an empty slot. The
    list has ENHANCEMENT_SLOTS entries, or more if the save has more."""
    equipment = get(props, SHIP_EQUIPMENT, [])
    found = list(equipment[ship]['Glyphs']['value']) if 0 <= ship < len(equipment) else []
    return found + [NO_GLYPH] * (ENHANCEMENT_SLOTS - len(found))


def enhancement_slots(props: Properties, game: GameData, ship: int) -> int | None:
    """The number of slots that the perk of the ship opens, or None if it is not known."""
    value = perk_value(props, game, ENHANCEMENT_PERK + SHIP_SUFFIX[ship]) if 0 <= ship < len(SHIP_SUFFIX) else None
    return None if value is None else int(value)


def set_enhancement(props: Properties, ship: int, slot: int, glyph: str) -> None:
    """Puts a glyph (or NONE) in a slot. The game does not put a glyph in two slots, so if the
    glyph is in a different slot, that slot becomes empty."""
    equipment = get(props, SHIP_EQUIPMENT, [])
    if not 0 <= ship < len(equipment):
        raise IndexError('the save has equipment for %d ships' % len(equipment))
    values = enhancements(props, ship)
    if not 0 <= slot < len(values):
        raise IndexError('a ship has %d enhancement slots' % len(values))
    if glyph != NO_GLYPH:
        values = [NO_GLYPH if v == glyph else v for v in values]
    values[slot] = glyph
    equipment[ship]['Glyphs']['value'] = values


def enhancement_problems(props: Properties, game: GameData, ship: int, slot: int) -> list[str]:
    """Why the game would not let the pilot put the glyph in this slot. The game still uses
    a glyph that is in the save."""
    glyph = enhancements(props, ship)[slot]
    if glyph == NO_GLYPH:
        return []
    out = []
    state = next((g for g in glyphs(props) if g['ID']['value'] == glyph), None)
    if state is None or not state['bUnlocked']['value']:
        out.append('The enhancement is locked.')
    if ship in game.glyph_by_id.get(glyph, {}).get('incompatible_ships', []):
        out.append('The enhancement is not for this ship.')
    count = enhancement_slots(props, game, ship)
    if count is not None and slot >= count:
        out.append('This slot is locked. The perks unlock %d slot%s.' % (count, '' if count == 1 else 's'))
    return out


# ---- the starting loadouts of each ship
#
# A ship has 3 starting loadouts: A (0), B (1) and C (2). UnlockedLoadout is the highest
# loadout that the pilot has unlocked for the ship. Loadout B unlocks when the pilot reaches
# sector 4 with the ship, and C at sector 7. SelectedLoadout is the loadout that the pilot chose
# in the hangar (WG_Loadouts.SelectLoadOut). The run save does not record the loadout:
# UGameplayLib::InitCurrentRunDataWithPawnDefaults reads SelectedLoadout when the run starts.
# It does not compare it with UnlockedLoadout. For a hardcore run, it uses loadout A.

LOADOUTS = 3
SELECTED_LOADOUT = 'SelectedLoadout'
UNLOCKED_LOADOUT = 'UnlockedLoadout'
LOADOUT_UNLOCK_SECTOR = [0, 4, 7]  # the sector that unlocks each loadout


def _ship_equipment(props: Properties, ship: int) -> Properties | None:
    equipment = get(props, SHIP_EQUIPMENT, [])
    return equipment[ship] if 0 <= ship < len(equipment) else None


def selected_loadout(props: Properties, ship: int) -> int:
    """The loadout that the pilot chose for a ship: 0 (A), 1 (B) or 2 (C)."""
    entry = _ship_equipment(props, ship)
    return int(get(entry, SELECTED_LOADOUT, 0)) if entry else 0


def unlocked_loadout(props: Properties, ship: int) -> int:
    """The highest loadout that the pilot has unlocked for a ship."""
    entry = _ship_equipment(props, ship)
    return int(get(entry, UNLOCKED_LOADOUT, 0)) if entry else 0


def set_selected_loadout(props: Properties, ship: int, index: int) -> None:
    """Sets the loadout that the pilot chose for a ship. The game uses a loadout that is not
    unlocked, so the editor does not prevent it."""
    entry = _ship_equipment(props, ship)
    if entry is None:
        raise IndexError('the save has equipment for %d ships' % len(get(props, SHIP_EQUIPMENT, [])))
    if not 0 <= index < LOADOUTS:
        raise IndexError('a ship has %d loadouts' % LOADOUTS)
    put(entry, SELECTED_LOADOUT, index)


# ---- resources the pilot keeps


def persistent_amount(props: Properties, path: str) -> int:
    for entry in get(props, PERSISTENT, []):
        if entry['PickupClass']['value'] == path:
            return int(entry['Amount']['value'])
    return 0


def pickup_entry(path: str, amount: int) -> Properties:
    """A new PickupEntry, as the game writes one for a resource."""
    return {
        'PickupClass': {'type': 'ObjectProperty', 'value': path},
        'Amount': {'type': 'IntProperty', 'value': amount},
        'bIsBlueprintForCrafting': {'type': 'BoolProperty', 'value': False},
        'QuestItem': {'type': 'ByteProperty<EQuestItem>', 'value': 'EQuestItem::None'},
    }


def set_pickup_amount(props: Properties, key: str, path: str, amount: int) -> None:
    """Sets the amount of a resource in the PickupEntry list `key`, and adds an entry for it if
    the list has none."""
    entries = props.setdefault(key, {'type': 'ArrayProperty<StructProperty<PickupEntry>>', 'value': []})['value']
    for entry in entries:
        if entry['PickupClass']['value'] == path:
            entry['Amount']['value'] = amount
            return
    entries.append(pickup_entry(path, amount))


def ship_perk(kind_perk: str, ship: int) -> str:
    """The id of the perk for one ship: 'Devices' and 2 give 'Devices Gunship'."""
    return kind_perk + SHIP_SUFFIX[ship]
