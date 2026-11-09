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

"""The pages of the pilot (CurrentPlayerSave.sav): the pilot, perks, blueprints, ships and
glyphs."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .. import profile, run
from ..gamedata import KINDS, LOADOUT_NAMES, SHIP_ICONS, SHIPS, GameData, short_name
from ..profile import get
from ..savegame import Properties
from .document import Document
from .gtk import GLib, Gtk

if TYPE_CHECKING:
    from .window import EditorWindow

VIRIDIAN = '/Game/Blueprints/Pickups/BP_PickupResourceOkkarEnergy.BP_PickupResourceOkkarEnergy_C'
INT_MAX = 2147483647
EDITABLE = [('DNAFragments', 'DNA fragments')]
STATS = [
    ('NumRuns', 'Runs'),
    ('NumWins', 'Wins'),
    ('LifeTimeKills', 'Kills'),
    ('MaxKills', 'Most kills in a run'),
    ('MaxCredits', 'Most credits'),
    ('MaxSector', 'Furthest sector'),
    ('TotalCreditsPickedUp', 'Credits picked up'),
    ('TotalPlayTime', 'Playing time'),
    ('Version', 'Saved by game version'),
]
KIND_TITLES = {
    'PrimaryWeapon': 'PRIMARY WEAPONS',
    'SecondaryWeapon': 'SECONDARY WEAPONS',
    'Device': 'DEVICES',
    'Consumable': 'CONSUMABLES',
    'Mod': 'MODS',
}
# The glyphs page and the enhancement slots do not show handicaps. The game never unlocks a
# handicap, and a hardcore run offers a handicap that is locked (see FORMAT.md).
GLYPH_TYPES = [('GLYPH', 'GLYPHS'), ('SUBROUTINE', 'SUB-ROUTINES')]
HANDICAP = 'HANDICAP'


def duration(seconds: int) -> str:
    return '%d h %02d min' % (seconds // 3600, seconds % 3600 // 60)


LOADOUT_NOTE = (
    'The game gives a regular run the starting loadout that the pilot chose for the ship, when the '
    'run starts. The run save does not record the loadout, so a change has no effect on a run that '
    'started. A hardcore run always starts with loadout A.'
)


def loadout_name(index: int, unlocked: int) -> str:
    """'Loadout B', and why it is locked if the pilot has not unlocked it. The game uses a
    locked loadout, so the editor offers it."""
    name = 'Loadout %s' % (LOADOUT_NAMES[index] if 0 <= index < len(LOADOUT_NAMES) else index)
    if index > unlocked and index < len(profile.LOADOUT_UNLOCK_SECTOR):
        name += ' (locked: reach sector %d with this ship to unlock it)' % profile.LOADOUT_UNLOCK_SECTOR[index]
    return name


def loadout_item(game: GameData, item: dict[str, Any]) -> str:
    """An item of a loadout: its name, and ×amount when there is more than one."""
    amount = int(item.get('amount', 1))
    return game.name(item['path']) + (' ×%d' % amount if amount > 1 else '')


@dataclass
class PerkRow:
    """The widgets of one perk on the perks page that a change of a perk level updates."""

    perk: profile.Perk
    grid: Gtk.Grid
    row: int
    name: Gtk.Box
    icon: Gtk.Widget | None
    unlocked: Gtk.CheckButton
    level: Gtk.SpinButton
    steps: Gtk.SpinButton | None
    benefit: Gtk.Box | None


class PilotPages:
    def __init__(self, window: EditorWindow) -> None:
        self.window = window
        self.perk_doc: Document | None = None  # the save of the perks page on show
        self.perk_rows: list[PerkRow] = []  # the perks on the perks page

    @property
    def doc(self) -> Document:
        doc = self.window.player
        if doc is None:
            raise RuntimeError("the pilot's save is not open")
        return doc

    def changed(self, refresh: bool = False) -> None:
        self.window.mark_dirty(self.doc)
        if refresh:
            self.window.refresh_soon()

    # ---- the pilot

    def show_pilot(self) -> None:
        from .window import label

        w = self.window
        props = self.doc.properties
        w.start_page('PILOT')
        grid = Gtk.Grid(column_spacing=16, row_spacing=8)
        row = 0
        with w.filling():
            if 'PlayerName' in props:
                grid.attach(label('Name', 'key'), 0, row, 1, 1)
                entry = Gtk.Entry(text=get(props, 'PlayerName'), max_length=40)
                entry.connect('changed', lambda e: self.set_value('PlayerName', e.get_text()))
                grid.attach(entry, 1, row, 1, 1)
                row += 1
            for key, title in EDITABLE:
                if key in props:
                    grid.attach(label(title, 'key'), 0, row, 1, 1)
                    grid.attach(
                        w.spin(get(props, key), 0, INT_MAX, lambda v, k=key: self.set_value(k, v)), 1, row, 1, 1
                    )
                    row += 1
            grid.attach(label(w.game.name(VIRIDIAN) if w.game else 'Viridian Energy', 'key'), 0, row, 1, 1)
            amount = profile.persistent_amount(props, VIRIDIAN)
            grid.attach(w.spin(amount, 0, INT_MAX, self.set_viridian, step=10), 1, row, 1, 1)
            row += 1
        w.page.append(grid)
        w.page.append(label('RECORDS', 'section-title'))
        stats = Gtk.Grid(column_spacing=16, row_spacing=6)
        for n, (key, title) in enumerate((k, t) for k, t in STATS if k in props):
            value = get(props, key)
            stats.attach(label(title, 'key'), 0, n, 1, 1)
            stats.attach(
                label(duration(value) if key == 'TotalPlayTime' else str(value), 'value', selectable=True), 1, n, 1, 1
            )
        w.page.append(stats)

    def set_value(self, key: str, value: object) -> None:
        if not self.window.busy:
            profile.put(self.doc.properties, key, value, 'StrProperty' if isinstance(value, str) else 'IntProperty')
            self.changed()

    def set_viridian(self, amount: int) -> None:
        profile.set_pickup_amount(self.doc.properties, profile.PERSISTENT, VIRIDIAN, amount)
        self.changed()

    # ---- perks

    def show_perks(self) -> None:
        self.show_perk_page(
            self.doc,
            'PERKS',
            'A level of a perk is bought in one step or in several. Setting the level clears the '
            'steps towards the next level. A perk that is bought opens the perks after it, as in '
            'the hangar.',
        )

    def show_hardcore_perks(self) -> None:
        """The perks of the hardcore run, which the run keeps apart from the pilot's."""
        doc = self.window.run_doc
        if doc is None:
            raise RuntimeError('the save of the hardcore run is not open')
        self.show_perk_page(
            doc,
            'HARDCORE PERKS',
            "A hardcore run has its own perks. The pilot's perks do not change them. The run starts "
            'with each perk at its hardcore level, and the ship gets its slots and values from '
            "these perks. The page shows the perks for all ships and the perks for the run's ship. "
            'The perks of the other ships have no effect on the run.',
        )

    def perks_changed(self, refresh: bool = False) -> None:
        if self.perk_doc:
            self.window.mark_dirty(self.perk_doc)
        if refresh:
            self.window.refresh_soon()

    def show_perk_page(self, doc: Document, page_title: str, note: str) -> None:
        from .window import label

        w = self.window
        self.perk_doc = doc
        hardcore = run.hardcore(doc.properties)
        w.start_page(page_title, note)
        self.perk_rows = []
        props = doc.properties
        all_perks = profile.perks(props, w.game)
        if not all_perks:
            w.page.append(label('This save has no perks.', 'warning'))
            return
        if not w.game:
            w.page.append(
                label(
                    "The game's data is not available, so the levels of the perks are not known.", 'warning', wrap=True
                )
            )
        bar = Gtk.Box(spacing=8)
        bar.append(w.button('Buy every level of every perk', self.max_perks))
        if hardcore:
            bar.append(w.button('Reset all perks to the hardcore starting values', self.hardcore_levels))
            spent = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
            spent.append(label('Credits spent on perks in this run', 'key'))
            with w.filling():
                spent.append(
                    w.spin(
                        get(props, run.PERK_CREDITS, 0), 0, INT_MAX, lambda v: self.set_perk_credits(int(v)), step=100
                    )
                )
            bar.append(spent)
        w.page.append(bar)
        shown = [(-1, 'ALL SHIPS')] + [(i, name.upper()) for i, name in enumerate(SHIPS)]
        if hardcore:
            shown = [(ship, title) for ship, title in shown if ship in (-1, run.ship(props))]
        with w.filling():
            for ship, title in shown:
                group = [p for p in all_perks if p.ship == ship]
                if not group:
                    continue
                w.page.append(label(title, 'section-title'))
                grid = Gtk.Grid(column_spacing=14, row_spacing=4)
                for n, perk in enumerate(group):
                    self.perk_row(grid, n, perk)
                w.page.append(grid)

    def perk_row(self, grid: Gtk.Grid, n: int, perk: profile.Perk) -> None:
        from .window import label

        w = self.window
        name = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        name.add_css_class('perk-row')
        name.set_valign(Gtk.Align.CENTER)
        if perk.locked:
            name.add_css_class('locked')
        name.append(label(perk.name, 'perk-name'))
        description = label(perk.definition.get('description', ''), 'perk-text', wrap=True)
        description.set_max_width_chars(34)
        name.append(description)
        name.set_tooltip_text('%s (%s)' % (perk.id, perk.definition.get('group', '')))
        name.set_size_request(250, -1)
        icon = w.icon_named(perk.definition.get('icon'), 36, 36)
        if icon:
            if perk.locked:
                icon.add_css_class('locked-icon')
            grid.attach(icon, 0, n, 1, 1)
        grid.attach(name, 1, n, 1, 1)
        unlocked = w.check('Unlocked', not perk.locked, lambda on, p=perk: self.set_locked(p, not on))
        unlocked.set_valign(Gtk.Align.CENTER)
        grid.attach(unlocked, 2, n, 1, 1)
        top = len(perk.levels) if perk.levels else 99
        level = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        level_spin = w.spin(perk.level, 0, top, lambda v, p=perk: self.set_level(p, v))
        level.append(level_spin)
        level.append(label('of %d' % len(perk.levels) if perk.levels else '', 'dim'))
        if self.perk_doc and run.hardcore(self.perk_doc.properties) and perk.definition:
            level.append(label('(hardcore %d)' % perk.hardcore, 'dim'))
        grid.attach(level, 3, n, 1, 1)
        steps_spin = None
        if perk.steps > 1:
            steps = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
            steps_spin = w.spin(perk.sublevel, 0, perk.steps - 1, lambda v, p=perk: self.set_sublevel(p, v))
            steps.append(steps_spin)
            steps.append(label('of %d steps' % perk.steps, 'dim'))
            grid.attach(steps, 4, n, 1, 1)
        benefit = None
        if perk.definition:
            benefit = self.perk_benefit(perk)
            grid.attach(benefit, 5, n, 1, 1)
        self.perk_rows.append(PerkRow(perk, grid, n, name, icon, unlocked, level_spin, steps_spin, benefit))

    def update_perk_rows(self, changed: profile.Perk) -> None:
        """Shows a change of a perk in the rows that are on show, and does not build the page
        again. The Level spin button of the perk keeps the focus. If the editor removed it,
        GTK would keep the window focus on the removed spin button. On Windows, Enter then
        goes to a widget that is not in the window, and GTK 4 can crash. A new level can
        unlock other perks, so all the rows get their locked state again."""
        with self.window.filling():
            for row in self.perk_rows:
                locked = row.perk.locked
                if locked:
                    row.name.add_css_class('locked')
                else:
                    row.name.remove_css_class('locked')
                if row.icon:
                    if locked:
                        row.icon.add_css_class('locked-icon')
                    else:
                        row.icon.remove_css_class('locked-icon')
                row.unlocked.set_active(not locked)
                if row.perk.entry is not changed.entry:
                    continue
                row.level.set_value(row.perk.level)
                if row.steps:
                    row.steps.set_value(row.perk.sublevel)
                if row.benefit:
                    # the benefit has only labels, which do not take the focus
                    row.grid.remove(row.benefit)
                    row.benefit = self.perk_benefit(row.perk)
                    row.grid.attach(row.benefit, 5, row.row, 1, 1)

    def perk_benefit(self, perk: profile.Perk) -> Gtk.Box:
        """What the perk gives at its level, and what the next level gives."""
        from .window import label

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        texts = perk.id in profile.LEVEL_TEXTS
        bullet = texts and perk.level > 0 and perk.id not in profile.REPLACING_TEXTS
        for line in perk.benefit():
            text = label(('• ' if bullet else '') + line, 'perk-benefit', wrap=True)
            text.set_max_width_chars(48)
            box.append(text)
        fmt = str(perk.definition.get('format', ''))
        notes = []
        base = perk.value(0)
        if not texts and perk.level and base:
            notes.append('Base %s' % profile.format_value(fmt, base))
        if perk.level < len(perk.levels):
            after = perk.benefit(perk.level + 1)
            notes.append('Next level: %s' % (after[-1] if texts else after[0]))
        elif perk.levels:
            notes.append('Last level')
        if notes:
            note = label('. '.join(notes) + ('' if notes[-1].endswith('.') else '.'), 'dim', wrap=True)
            note.set_max_width_chars(48)
            box.append(note)
        return box

    @property
    def perk_props(self) -> Properties:
        return (self.perk_doc or self.doc).properties

    def set_level(self, perk: profile.Perk, level: int) -> None:
        profile.set_perk_level(self.perk_props, self.window.game, perk, level)
        self.perks_changed()
        self.update_perk_rows(perk)

    def set_sublevel(self, perk: profile.Perk, steps: int) -> None:
        profile.set_perk_sublevel(perk, steps)
        self.perks_changed()

    def set_locked(self, perk: profile.Perk, locked: bool) -> None:
        profile.set_perk_locked(perk, locked)
        self.perks_changed()
        self.update_perk_rows(perk)

    def set_perk_credits(self, credits: int) -> None:
        run.set_value(self.perk_props, run.PERK_CREDITS, credits)
        self.perks_changed()

    def max_perks(self) -> None:
        def go() -> None:
            n = profile.max_all_perks(self.perk_props, self.window.game)
            self.window.set_status('Bought every level of %d perks' % n)
            if n:
                self.perks_changed(refresh=True)

        self.window.confirm('Buy every perk?', 'Every perk is unlocked and set to its last level.', 'Buy all', go)

    def hardcore_levels(self) -> None:
        def go() -> None:
            n = profile.set_hardcore_levels(self.perk_props, self.window.game)
            self.window.set_status('Reset %d perks to the hardcore starting values' % n)
            if n:
                self.perks_changed(refresh=True)

        self.window.confirm(
            'Reset all perks?',
            'Every perk is unlocked and set to the level that a hardcore run starts with. The steps '
            'towards the next level are cleared.',
            'Reset perks',
            go,
        )

    # ---- blueprints

    def show_blueprints(self) -> None:
        from .window import label

        w = self.window
        w.start_page('BLUEPRINTS', 'The items the hangar can give as blueprints at the start of a run.')
        props = self.doc.properties
        have = set(profile.blueprints(props))
        bar = Gtk.Box(spacing=8)
        bar.append(w.button('Unlock all', lambda: self.set_all(True)))
        bar.append(w.button('Lock all', lambda: self.set_all(False)))
        w.page.append(bar)
        offered = set(w.game.blueprints())
        with w.filling():
            for kind in KINDS:
                paths = [p for p in w.game.items(kind) if p in offered]
                if not paths:
                    continue
                w.page.append(
                    label('%s  (%d of %d)' % (KIND_TITLES[kind], len(have & set(paths)), len(paths)), 'section-title')
                )
                w.page.append(self.check_grid(paths, have))
            others = sorted(have - offered)
            if others:
                w.page.append(label('OTHERS IN THE SAVE', 'section-title'))
                w.page.append(self.check_grid(others, have))

    def check_grid(self, paths: list[str], have: set[str]) -> Gtk.FlowBox:
        w = self.window
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=2)
        flow.set_max_children_per_line(4)
        flow.set_min_children_per_line(2)
        for path in paths:
            tier = w.game.equipment.get(path, {}).get('tier', 0)
            check = w.check(w.game.name(path), path in have, lambda on, p=path: self.set_blueprint(p, on))
            check.set_tooltip_text(short_name(path))
            if tier:
                check.add_css_class('tier-%d' % tier)
            icon = w.icon(path, 39, 27)
            if icon:
                box = Gtk.Box(spacing=6)
                box.append(icon)
                box.append(check)
                flow.append(box)
            else:
                flow.append(check)
        return flow

    def set_blueprint(self, path: str, unlocked: bool) -> None:
        profile.set_blueprint(self.doc.properties, path, unlocked)
        self.changed()

    def set_all(self, unlocked: bool) -> None:
        props = self.doc.properties
        for path in self.window.game.blueprints():
            profile.set_blueprint(props, path, unlocked)
        self.changed(refresh=True)

    # ---- ships

    def show_ships(self) -> None:
        from .window import label

        w = self.window
        w.start_page(
            'SHIPS',
            'The game has a step that unlocks the starter perks of a ship '
            '(UnlockStarterPerksForShip). The editor does not do that step when it unlocks a ship. '
            'If perks of the ship stay locked, unlock them on the Perks page.\n' + LOADOUT_NOTE,
        )
        props = self.doc.properties
        runs = get(props, 'RunsPerShipIndex', [])
        equipment = get(props, profile.SHIP_EQUIPMENT, [])
        grid = Gtk.Grid(column_spacing=16, row_spacing=10)
        self.enhancement_boxes: dict[int, Gtk.Box] = {}
        self.loadout_boxes: dict[int, Gtk.Box] = {}
        with w.filling():
            for i, unlocked in enumerate(profile.ships(props)):
                row = 2 * i
                name = SHIPS[i] if i < len(SHIPS) else 'Ship %d' % i
                icon = w.icon_named(SHIP_ICONS[i] if i < len(SHIP_ICONS) else None, 50, 50)
                if icon:
                    if not unlocked:
                        icon.add_css_class('locked-icon')
                    grid.attach(icon, 0, row, 1, 1)
                grid.attach(label(name, 'strong'), 1, row, 1, 1)
                grid.attach(w.switch(unlocked, lambda on, n=i: self.set_ship(n, on)), 2, row, 1, 1)
                grid.attach(label('%d runs' % runs[i] if i < len(runs) else '', 'dim'), 3, row, 1, 1)
                if i < len(equipment):
                    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                    box.set_margin_bottom(8)
                    self.enhancement_boxes[i] = box
                    self.fill_enhancements(i)
                    loadout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                    loadout.set_margin_bottom(8)
                    self.loadout_boxes[i] = loadout
                    self.fill_loadout(i)
                    details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                    details.append(box)
                    details.append(loadout)
                    grid.attach(details, 1, row + 1, 3, 1)
        w.page.append(grid)

    def fill_enhancements(self, ship: int) -> None:
        """The enhancement slots of a ship: a choice of glyph for each, and why the game
        would not allow a choice."""
        from .window import clear, label

        w = self.window
        props = self.doc.properties
        box = self.enhancement_boxes[ship]
        clear(box)
        count = profile.enhancement_slots(props, w.game, ship)
        title = 'ENHANCEMENT SLOTS'
        if count is not None:
            title += ': %d OF %d UNLOCKED' % (count, len(profile.enhancements(props, ship)))
        box.append(label(title, 'slot-label'))
        chosen = profile.enhancements(props, ship)
        for slot, glyph in enumerate(chosen):
            # The game does not put an enhancement in two slots, so a slot does not offer the
            # enhancements of the other slots. The hangar installs only an unlocked glyph, and
            # the game never unlocks a handicap, so a slot offers no handicap. A slot that has
            # one still shows it.
            others = set(chosen[:slot] + chosen[slot + 1 :]) - {profile.NO_GLYPH}
            offered = [
                g for g in w.game.glyphs if g['id'] not in others and (g.get('type') != HANDICAP or g['id'] == glyph)
            ]
            ids = [profile.NO_GLYPH] + [g['id'] for g in offered]
            names = ['Empty'] + ['%s (%s)' % (g['name'], g['type'].lower()) for g in offered]
            line = Gtk.Box(spacing=8)
            icon = w.icon_named(w.game.glyph_by_id.get(glyph, {}).get('icon'), 28, 28)
            if icon:
                line.append(icon)
            else:
                spacer = Gtk.Box()
                spacer.set_size_request(28, 28)
                line.append(spacer)
            choice = w.dropdown(ids, names, glyph, lambda g, s=slot: self.set_enhancement(ship, s, g), search=True)
            choice.set_size_request(280, -1)
            line.append(choice)
            problems = profile.enhancement_problems(props, w.game, ship, slot)
            if problems:
                line.append(label(' '.join(problems), 'warning', wrap=True))
            box.append(line)

    def set_enhancement(self, ship: int, slot: int, glyph: str) -> None:
        profile.set_enhancement(self.doc.properties, ship, slot, glyph)
        self.window.mark_dirty(self.doc)
        # Refresh after the dropdown's signal returns: the dropdown is part of what is rebuilt.
        GLib.idle_add(self.refill_enhancements, ship)

    def refill_enhancements(self, ship: int) -> bool:
        with self.window.filling():
            self.fill_enhancements(ship)
        return False

    def fill_loadout(self, ship: int) -> None:
        """The starting loadout that the pilot chose for a ship, and its items."""
        from .window import clear, label

        w = self.window
        props = self.doc.properties
        box = self.loadout_boxes[ship]
        clear(box)
        unlocked = profile.unlocked_loadout(props, ship)
        box.append(label('STARTING LOADOUT: %d OF %d UNLOCKED' % (unlocked + 1, profile.LOADOUTS), 'slot-label'))
        selected = profile.selected_loadout(props, ship)
        choices = list(range(profile.LOADOUTS))
        names = [loadout_name(i, unlocked) for i in choices]
        choice = w.dropdown(choices, names, selected, lambda n: self.set_loadout(ship, n))
        choice.set_halign(Gtk.Align.START)
        box.append(choice)
        items = w.game.loadout(ship, selected)
        if items:
            text = label(', '.join(loadout_item(w.game, i) for i in items), 'dim', wrap=True, selectable=True)
            text.set_max_width_chars(70)
            box.append(text)

    def set_loadout(self, ship: int, index: int) -> None:
        profile.set_selected_loadout(self.doc.properties, ship, index)
        self.window.mark_dirty(self.doc)
        # Refresh after the dropdown's signal returns: the dropdown is part of what is rebuilt.
        GLib.idle_add(self.refill_loadout, ship)

    def refill_loadout(self, ship: int) -> bool:
        with self.window.filling():
            self.fill_loadout(ship)
        return False

    def set_ship(self, index: int, unlocked: bool) -> None:
        profile.set_ship(self.doc.properties, index, unlocked)
        self.changed(refresh=True)

    # ---- glyphs

    def show_glyphs(self) -> None:
        from .window import label

        w = self.window
        w.start_page(
            'GLYPHS AND ENHANCEMENTS',
            'The hangar can give a glyph that is unlocked. The page does not show the handicaps of '
            'hardcore runs: the game does not lock or unlock them.',
        )
        entries = profile.glyphs(self.doc.properties)
        bar = Gtk.Box(spacing=8)
        bar.append(w.button('Unlock all', lambda: self.set_all_glyphs(True)))
        w.page.append(bar)
        with w.filling():
            for kind, title in GLYPH_TYPES + [('', 'OTHERS')]:
                rows = [e for e in entries if w.game.glyph_by_id.get(e['ID']['value'], {}).get('type', '') == kind]
                if not rows:
                    continue
                w.page.append(label(title, 'section-title'))
                grid = Gtk.Grid(column_spacing=14, row_spacing=4)
                for n, entry in enumerate(rows):
                    glyph = w.game.glyph_by_id.get(entry['ID']['value'], {})
                    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                    text.append(label(glyph.get('name') or entry['ID']['value'], 'perk-name'))
                    effect = glyph.get('positive', '')
                    if glyph.get('negative'):
                        effect += '  ' + glyph['negative']
                    if effect:
                        text.append(label(effect, 'perk-text', wrap=True))
                    text.set_hexpand(True)
                    icon = w.icon_named(glyph.get('icon'), 40, 40)
                    if icon:
                        grid.attach(icon, 0, n, 1, 1)
                    grid.attach(text, 1, n, 1, 1)
                    grid.attach(
                        w.check('Unlocked', entry['bUnlocked']['value'], lambda on, e=entry: self.set_glyph(e, on)),
                        2,
                        n,
                        1,
                        1,
                    )
                w.page.append(grid)

    def set_glyph(self, entry: dict[str, dict[str, object]], unlocked: bool) -> None:
        profile.set_glyph(entry, unlocked)
        self.changed()

    def set_all_glyphs(self, unlocked: bool) -> None:
        game = self.window.game
        for entry in profile.glyphs(self.doc.properties):
            if game.glyph_by_id.get(entry['ID']['value'], {}).get('type') != HANDICAP:
                profile.set_glyph(entry, unlocked=unlocked)
        self.changed(refresh=True)
