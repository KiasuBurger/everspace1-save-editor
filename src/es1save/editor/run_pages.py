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

"""The run page of the regular run (CurrentRunSave.sav) or the hardcore run (CurrentHCRunSave.sav),
with the buffs, and the handicaps of a hardcore run. loadout_page.py has the ship's
equipment and resources, and bonus_page.py has the bonus gear of a run that has not started."""

from typing import TYPE_CHECKING

from .. import run
from ..gamedata import SHIP_ICONS, SHIPS, GameData, short_name
from ..profile import get
from ..savegame import Properties
from .document import Document
from .gtk import Gtk

if TYPE_CHECKING:
    from .window import EditorWindow

INT_MAX = 2147483647
NUMBERS = [('Credits', 'Credits', 100), ('FuelAmount', 'Fuel', 10)]
LOCATION_TIP = (
    'The column of the location in the map of the sector, and the number of columns. A sector can '
    'have more than one location in a column. A path visits one location in each column, and '
    'some paths skip a column.'
)
RAW_WHERE = [('CurrentSystem', 'System ID'), ('CurrentLocation', 'Location ID')]
SLOT_ADDED = 'The game added the slot. If you remove the buff, the slot stays.'
SLOT_PENDING = 'The game adds the slot when it loads the run.'
HANDICAP_NOTE = (
    'The game applies only the first handicap of the list. The other handicaps are a record of the earlier '
    'handicaps of the run. A new handicap goes to the top of the list, as in the game. After system 5, no '
    'handicap is active.'
)


def clock(seconds: float) -> str:
    """A time as the game shows the lifetime of a buff: 00:10:00."""
    whole = int(seconds)
    return '%02d:%02d:%02d' % (whole // 3600, whole % 3600 // 60, whole % 60)


def buff_lifetime(game: GameData, path: str) -> str:
    """The lifetime of a buff as the tuning station shows it: 00:10:00, or This run."""
    total = float(game.equipment.get(path, {}).get('duration', 0))
    return clock(total) if total else 'This run'


def where_rows(props: Properties) -> list[tuple[str, str]]:
    """The difficulty, the place on the map and the playing time, as titles and texts. The place
    is the sector and the column of the location in the map of the sector. If the map does not have them, the rows
    show CurrentSystem and CurrentLocation as the save has them."""
    from .pilot_pages import duration

    rows = []
    if 'Difficulty' in props:
        rows.append(('Difficulty', str(get(props, 'Difficulty')).split('::')[-1]))
    where = run.position(props)
    if where:
        rows += [('Sector', str(where.sector)), ('Location', '%d of %d' % (where.location, where.columns))]
    else:
        rows += [(title, str(get(props, key))) for key, title in RAW_WHERE if key in props]
    if 'DurationSeconds' in props:
        rows.append(('Playing time', duration(get(props, 'DurationSeconds'))))
    return rows


class RunPages:
    def __init__(self, window: EditorWindow) -> None:
        self.window = window

    @property
    def doc(self) -> Document:
        doc = self.window.run_doc
        if doc is None:
            raise RuntimeError('the save of the run is not open')
        return doc

    @property
    def props(self) -> Properties:
        return self.doc.properties

    def changed(self, refresh: bool = False) -> None:
        self.window.mark_dirty(self.doc)
        if refresh:
            self.window.update_counts()
            self.window.refresh_soon()

    # ---- the run

    def show_run(self) -> None:
        from .window import label

        w = self.window
        props = self.props
        ship = run.ship(props)
        hardcore = run.hardcore(props)
        w.start_page('HARDCORE RUN' if hardcore else 'CURRENT RUN')
        if not run.started(props):
            w.page.append(
                label(
                    'This run has not started yet. The game gives the ship its equipment when the run '
                    'starts. Until then, only the bonus gear can be changed.',
                    'warning',
                    wrap=True,
                )
            )
        grid = Gtk.Grid(column_spacing=16, row_spacing=8)
        row = 0
        grid.attach(label('Ship', 'key'), 0, row, 1, 1)
        name = Gtk.Box(spacing=10)
        icon = w.icon_named(SHIP_ICONS[ship] if 0 <= ship < len(SHIP_ICONS) else None, 40, 40)
        if icon:
            name.append(icon)
        name.append(label(SHIPS[ship] if 0 <= ship < len(SHIPS) else str(ship), 'strong'))
        grid.attach(name, 1, row, 1, 1)
        row += 1
        for title, text in where_rows(props):
            grid.attach(label(title, 'key'), 0, row, 1, 1)
            value = label(text, 'value', selectable=True)
            if title == 'Location' and ' of ' in text:
                value.set_tooltip_text(LOCATION_TIP)
            grid.attach(value, 1, row, 1, 1)
            row += 1
        if run.started(props):
            with w.filling():
                for key, title, step in NUMBERS:
                    grid.attach(label(title, 'key'), 0, row, 1, 1)
                    spin = w.spin(get(props, key, 0), 0, INT_MAX, lambda v, k=key: self.set_value(k, int(v)), step=step)
                    grid.attach(spin, 1, row, 1, 1)
                    row += 1
                if 'PlayerHealthRatio' in props:
                    grid.attach(label('Hull (%)', 'key'), 0, row, 1, 1)
                    health = w.spin(
                        get(props, 'PlayerHealthRatio') * 100,
                        1,
                        100,
                        lambda v: self.set_value('PlayerHealthRatio', v / 100),
                        1,
                    )
                    grid.attach(health, 1, row, 1, 1)
                    row += 1
        w.page.append(grid)
        if hardcore:
            with w.filling():
                w.page.append(self.handicaps_box())
        if run.started(props):
            with w.filling():
                w.page.append(self.buffs_box())

    def handicaps_box(self) -> Gtk.Box:
        """The handicaps of a hardcore run, with a row for each, and a row to add one."""
        from .window import label

        w = self.window
        game = w.game
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(label('HANDICAPS', 'section-title'))
        chosen = run.handicaps(self.props)
        active = run.active_handicap(self.props)
        if not chosen:
            box.append(label('The run has no handicaps.', 'dim'))
        elif active is None:
            box.append(label('No handicap is active: the run is past system 5.', 'dim'))
        grid = Gtk.Grid(column_spacing=16, row_spacing=8)
        for row, glyph in enumerate(chosen):
            info = game.glyph_by_id.get(glyph, {})
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title = label(info.get('name') or glyph.split('::')[-1], 'strong')
            title.set_tooltip_text(glyph)
            if row == 0 and active is not None:
                head = Gtk.Box(spacing=8)
                head.append(title)
                badge = label('ACTIVE', 'badge')
                badge.set_valign(Gtk.Align.CENTER)
                head.append(badge)
                cell.append(head)
            else:
                cell.append(title)
            if info.get('negative'):
                text = label(info['negative'], 'dim', wrap=True)
                text.set_max_width_chars(50)
                cell.append(text)
            grid.attach(cell, 0, row, 1, 1)
            remove = w.button('Remove', lambda i=row: self.remove_handicap(i), 'danger')
            remove.set_valign(Gtk.Align.START)
            grid.attach(remove, 1, row, 1, 1)
        box.append(grid)
        offered = run.handicap_choices(self.props, game)
        if offered:
            picked = [offered[0]]
            names = [game.glyph_by_id[g]['name'] for g in offered]
            add = Gtk.Box(spacing=10)
            add.append(w.dropdown(offered, names, offered[0], lambda g: picked.__setitem__(0, g), True))
            add.append(w.button('Add handicap', lambda: self.add_handicap(picked[0])))
            box.append(add)
        elif not game.glyphs:
            box.append(label("The game's data is not available, so the editor cannot offer handicaps.", 'warning'))
        box.append(label(HANDICAP_NOTE, 'dim', wrap=True))
        return box

    def add_handicap(self, glyph: str) -> None:
        run.add_handicap(self.props, glyph)
        self.changed(refresh=True)

    def remove_handicap(self, index: int) -> None:
        run.remove_handicap(self.props, index)
        self.changed(refresh=True)

    def buffs_box(self) -> Gtk.Box:
        """The buffs (ship upgrades) of the run, with a row for each, and a row to add one. All
        buffs have the same icon, so each row shows the buff's name."""
        from .window import label

        w = self.window
        game = w.game
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(label('BUFFS (SHIP UPGRADES)', 'section-title'))
        entries = run.buffs(self.props)
        grid = Gtk.Grid(column_spacing=16, row_spacing=8)
        if entries:
            for col, title in enumerate(['Buff', 'Lifetime', 'Time left (s)']):
                grid.attach(label(title, 'key'), col, 0, 1, 1)
        else:
            box.append(label('The run has no buffs.', 'dim'))
        for row, entry in enumerate(entries, 1):
            path = entry['Class']['value']
            info = game.equipment.get(path, {})
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            name = Gtk.Box(spacing=8)
            icon = w.icon(path, 24, 24)
            if icon:
                name.append(icon)
            title = label(game.name(path), 'strong')
            title.set_tooltip_text(short_name(path))
            name.append(title)
            cell.append(name)
            if info.get('description'):
                text = label(info['description'], 'dim', wrap=True)
                text.set_max_width_chars(40)
                cell.append(text)
            grid.attach(cell, 0, row, 1, 1)
            lifetime = label(buff_lifetime(game, path), 'value')
            lifetime.set_valign(Gtk.Align.START)
            grid.attach(lifetime, 1, row, 1, 1)
            total = float(info.get('duration', 0))
            if total:
                current = float(get(entry, 'CurrentDuration', 0.0))
                # At 0 the game removes a timed buff, so the least is 1 second. The game does not
                # compare the time with the lifetime, so the time can be more than the lifetime.
                spin = w.spin(round(current), 1, INT_MAX, lambda v, e=entry: self.set_buff_time(e, v))
                spin.set_valign(Gtk.Align.START)
                grid.attach(spin, 2, row, 1, 1)
            elif run.SLOT_BUFFS.get(short_name(path)):
                note = SLOT_ADDED if run.buff_installed(entry) else SLOT_PENDING
                text = label(note, 'dim', wrap=True)
                text.set_valign(Gtk.Align.START)
                grid.attach(text, 2, row, 1, 1)
            remove = w.button('Remove', lambda e=entry: self.remove_buff(e), 'danger')
            remove.set_valign(Gtk.Align.START)
            grid.attach(remove, 3, row, 1, 1)
        box.append(grid)
        offered = game.items('Buff')
        if not offered:
            box.append(label("The game's data is not available, so the editor cannot offer buffs.", 'warning'))
            return box
        chosen = [offered[0]]
        add = Gtk.Box(spacing=10)
        add.append(
            w.dropdown(offered, [game.name(p) for p in offered], offered[0], lambda p: chosen.__setitem__(0, p), True)
        )
        add.append(w.button('Add buff', lambda: self.add_buff(chosen[0])))
        box.append(add)
        box.append(
            label(
                'The game installs a new buff when it loads the run. A timed buff starts with its full time.',
                'dim',
                wrap=True,
            )
        )
        return box

    def add_buff(self, path: str) -> None:
        run.add_buff(self.props, self.window.game, path)
        self.changed(refresh=True)

    def remove_buff(self, entry: Properties) -> None:
        run.remove_buff(self.props, entry)
        self.changed(refresh=True)

    def set_buff_time(self, entry: Properties, seconds: float) -> None:
        run.set_buff_time(entry, seconds)
        self.changed()

    def set_value(self, key: str, value: float) -> None:
        run.set_value(self.props, key, value)
        self.changed()
