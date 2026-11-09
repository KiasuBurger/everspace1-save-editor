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

"""The loadout of the run's ship, laid out as the Everspace 2 editor lays out a ship.

The page shows a tile for each slot of the weapons, devices and consumables, and a tile for
each resource that a run can hold. The panel at the right shows the selected tile: the card
and the controls of an item, the items that an empty slot can take, or the amount of a
resource.
"""

from typing import TYPE_CHECKING

from .. import attributes, profile, run
from ..gamedata import SHIP_ICONS, SHIPS, short_name
from ..profile import get
from ..run import Slots
from ..savegame import Properties
from .document import Document
from .gtk import Gdk, Gtk

if TYPE_CHECKING:
    from .window import EditorWindow

Key = tuple[str, int | str]  # of a tile: (the kind of the slot, its index) or ('Resource', path)
RESOURCE = 'Resource'
TILE = 86
LIMIT_NOTE = (
    'The ship of the run holds %d. The game keeps a larger amount from the save, '
    'but the ship usually collects no more until it has less than %d.'
)


class Tile(Gtk.Button):
    """One slot or resource, drawn like a slot of the game: the tier as the colour of the
    border, the icon, and the amount in the corner."""

    def __init__(self, page: LoadoutPage, key: Key) -> None:
        super().__init__()
        self.page = page
        self.key = key
        self.add_css_class('tile')
        self.set_size_request(TILE, TILE)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.START)
        self.connect('clicked', lambda _b: page.select(key))
        self.corner = Gtk.Label(xalign=0.5)
        self.corner.add_css_class('amount')
        self.corner.set_halign(Gtk.Align.END)
        self.corner.set_valign(Gtk.Align.END)
        self.name = ''

    def show_item(self, texture: Gdk.Texture | None, name: str, tier: int, mods: int, corner: str) -> None:
        if tier:
            self.add_css_class('tier-%d' % tier)
        overlay = Gtk.Overlay()
        overlay.set_size_request(TILE - 4, TILE - 4)
        overlay.set_child(self.picture(texture, 76, 53, name))
        if mods:
            mark = Gtk.Label(label='+%d' % mods)
            mark.add_css_class('mark')
            mark.set_halign(Gtk.Align.START)
            mark.set_valign(Gtk.Align.START)
            mark.set_tooltip_text('%d mods' % mods)
            overlay.add_overlay(mark)
        self.corner.set_label(corner)
        self.corner.set_visible(bool(corner))
        overlay.add_overlay(self.corner)
        self.set_child(overlay)

    def show_empty(self, extra: bool = False) -> None:
        self.add_css_class('empty')
        if extra:
            self.add_css_class('extra')

    def show_resource(self, texture: Gdk.Texture | None, name: str, amount: int) -> None:
        self.add_css_class('resource')
        self.name = name
        overlay = Gtk.Overlay()
        overlay.set_size_request(TILE - 4, TILE - 4)
        overlay.set_child(self.picture(texture, 60, 60, name))
        overlay.add_overlay(self.corner)
        self.set_child(overlay)
        self.set_amount(amount)

    def set_amount(self, amount: int) -> None:
        """Shows a new amount of a resource. A resource that the run has none of is dim."""
        self.corner.set_label(str(amount))
        if amount:
            self.remove_css_class('none')
        else:
            self.add_css_class('none')
        self.set_tooltip_text('%s: %d' % (self.name, amount))

    @staticmethod
    def picture(texture: Gdk.Texture | None, width: int, height: int, name: str) -> Gtk.Widget:
        from .window import Icon, label

        if texture:
            return Icon(texture, width, height)
        text = label(name, 'placeholder', wrap=True, xalign=0.5)
        text.set_max_width_chars(9)
        text.set_justify(Gtk.Justification.CENTER)
        text.set_valign(Gtk.Align.CENTER)
        return text


class LoadoutPage:
    def __init__(self, window: EditorWindow) -> None:
        self.window = window
        self.selection: Key | None = None
        self.tiles: dict[Key, Tile] = {}
        self.limit_note: tuple[Gtk.Label, int] | None = None  # in the panel of a resource with a limit

    @property
    def doc(self) -> Document:
        doc = self.window.run_doc
        if doc is None:
            raise RuntimeError('the save of the run is not open')
        return doc

    @property
    def props(self) -> Properties:
        return self.doc.properties

    def limits(self, slots: Slots) -> tuple[int | None, int]:
        """The number of slots and the number of mods on one item, for the run's ship."""
        player = self.window.perk_props()
        ship = run.ship(self.props)
        game = self.window.game
        limit = run.slot_limit(player, game, slots, ship)
        if limit is not None:
            limit += run.buff_slots(self.props, slots)
        return limit, run.mod_limit(player, game, slots, ship)

    def changed(self, refresh: bool = False) -> None:
        self.window.mark_dirty(self.doc)
        if refresh:
            self.window.update_counts()
            self.window.refresh_soon()

    # ---- the page

    def show(self) -> None:
        from .window import label

        w = self.window
        ship = run.ship(self.props)
        clear_box(w.page)
        top = Gtk.Box(spacing=12)
        icon = w.icon_named(SHIP_ICONS[ship] if 0 <= ship < len(SHIP_ICONS) else None, 40, 40)
        if icon:
            top.append(icon)
        title = label((SHIPS[ship] if 0 <= ship < len(SHIPS) else 'Ship %d' % ship).upper(), 'page-title')
        title.set_valign(Gtk.Align.CENTER)
        top.append(title)
        w.page.append(top)
        self.tiles = {}
        limits = {slots.kind: self.limits(slots)[0] for slots in run.SLOTS}
        if any(limit is None for limit in limits.values()):
            w.page.append(
                label(
                    'The editor cannot tell how many slots the ship has: the perks are not open, or '
                    'the game data does not have the slots of this ship.',
                    'dim',
                    wrap=True,
                )
            )
        w.page.append(label('EQUIPPED', 'section-title'))
        # one kind on each row: the Sentinel's 6 devices fill the width of the default window
        for slots in run.SLOTS:
            w.page.append(self.slot_group(slots, limits[slots.kind]))
        w.page.append(label('RESOURCES', 'section-title'))
        w.page.append(self.resource_tiles(run.resources(self.props, w.game)))
        if self.selection not in self.tiles:
            self.selection = None
        self.mark_selection()
        self.build_detail()
        w.detail_scroll.set_visible(True)

    def resource_tiles(self, amounts: list[tuple[str, int]]) -> Gtk.Box:
        """A tile for each resource, with one row for each group of the game's resource bar."""
        w = self.window
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for group in run.resource_rows(amounts):
            row = Gtk.Box(spacing=6)
            for path, amount in group:
                tile = Tile(self, (RESOURCE, path))
                tile.show_resource(w.icons.item(w.game, path), w.game.name(path), amount)
                self.tiles[tile.key] = tile
                row.append(tile)
            rows.append(row)
        return rows

    def slot_group(self, slots: Slots, limit: int | None) -> Gtk.Box:
        """The label and the tiles of one kind of slot."""
        from .window import label

        w = self.window
        game = w.game
        entries = get(self.props, slots.key, [])
        count = run.slot_count(self.props, slots, limit)
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = slots.label.upper()
        if limit is not None and len(run.items(self.props, slots)) > limit:
            title += '  (MORE ITEMS THAN SLOTS)'
        group.append(label(title, 'slot-label'))
        row = Gtk.Box(spacing=6)
        key = run.amount_key(slots)
        for index in range(count):
            tile = Tile(self, (slots.kind, index))
            entry = entries[index] if index < len(entries) else None
            extra = limit is not None and index >= limit
            if entry is None or run.is_empty(entry):
                tile.show_empty(extra)
                tile.set_tooltip_text('Empty slot: click to add an item')
            else:
                path = entry['Class']['value']
                info = game.equipment.get(path, {})
                corner = str(entry[key]['value']) if key and key in entry else ''
                mods = run.mods(entry)
                tile.show_item(w.icons.item(game, path), game.name(path), info.get('tier', 0), len(mods), corner)
                tip = game.name(path) + ('\nTier %d' % info['tier'] if info.get('tier') else '')
                tip += ''.join('\n+ ' + game.name(m) for m in mods)
                tile.set_tooltip_text(tip)
                if extra:
                    tile.add_css_class('extra')
            self.tiles[tile.key] = tile
            row.append(tile)
        group.append(row)
        return group

    def select(self, key: Key | None) -> None:
        self.selection = key
        self.mark_selection()
        self.build_detail()

    def mark_selection(self) -> None:
        for key, tile in self.tiles.items():
            if key == self.selection:
                tile.add_css_class('selected')
            else:
                tile.remove_css_class('selected')

    # ---- the panel

    def build_detail(self) -> None:
        from .window import label

        w = self.window
        box = w.detail
        clear_box(box)
        key = self.selection
        if key is None:
            box.append(label('Select an item to see and change it.\nClick an empty slot to add one.', 'dim', wrap=True))
            return
        kind, where = key
        with w.filling():
            if kind == RESOURCE and isinstance(where, str):
                self.resource_detail(box, where)
                return
            slots = run.SLOTS_BY_KIND[kind]
            entries = get(self.props, slots.key, [])
            index = int(where)
            entry = entries[index] if index < len(entries) else None
            if entry is None or run.is_empty(entry):
                self.empty_detail(box, slots, index)
            else:
                self.item_detail(box, slots, entry)

    def resource_detail(self, box: Gtk.Box, path: str) -> None:
        from .window import label

        w = self.window
        amount = dict(run.resources(self.props, w.game)).get(path, 0)
        card = self.card(path, w.game.name(path), 'Resource', 0, 60, 60)
        box.append(card)
        row = Gtk.Box(spacing=10)
        row.append(label('Amount', 'key'))
        row.append(w.spin(amount, 0, 99999, lambda v: self.set_resource(path, v)))
        box.append(row)
        self.limit_note = None
        limit = run.resource_limit(self.props, w.game, path)
        if limit is not None:
            row = Gtk.Box(spacing=10)
            row.append(label('Ship limit', 'key'))
            row.append(label(str(limit), 'value'))
            box.append(row)
            note = label(LIMIT_NOTE % (limit, limit), 'dim', wrap=True)
            note.set_max_width_chars(40)
            box.append(note)
            self.limit_note = (note, limit)
            self.mark_limit(amount)

    def mark_limit(self, amount: int) -> None:
        """Shows the note on the limit as a warning when the amount is more than the limit."""
        if self.limit_note is None:
            return
        note, limit = self.limit_note
        if amount > limit:
            note.remove_css_class('dim')
            note.add_css_class('warning')
        else:
            note.remove_css_class('warning')
            note.add_css_class('dim')

    def empty_detail(self, box: Gtk.Box, slots: Slots, index: int) -> None:
        from .window import label

        w = self.window
        box.append(label('EMPTY SLOT', 'section-title'))
        box.append(label('%s, slot %d' % (slots.label, index + 1), 'dim'))
        offered = w.game.items(slots.kind)
        if not offered:
            box.append(label("The game's data is not available, so the editor cannot offer items.", 'warning'))
            return
        chosen = [offered[0]]
        box.append(
            w.dropdown(offered, self.names(offered), offered[0], lambda p: chosen.__setitem__(0, p), search=True)
        )
        add = w.button('Add', lambda: self.add_item(slots, index, chosen[0]))
        add.set_halign(Gtk.Align.START)
        box.append(add)

    def item_detail(self, box: Gtk.Box, slots: Slots, entry: Properties) -> None:
        from .window import label

        w = self.window
        game = w.game
        path = entry['Class']['value']
        info = game.equipment.get(path, {})
        box.append(self.card(path, game.name(path), run.kind_name(game, path), info.get('tier', 0), 104, 72))
        offered = game.items(slots.kind)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        row = 0
        if offered:
            grid.attach(label('Item', 'key'), 0, row, 1, 1)
            grid.attach(
                w.dropdown(offered, self.names(offered), path, lambda p: self.replace_item(entry, p), search=True),
                1,
                row,
                1,
                1,
            )
            row += 1
        key = run.amount_key(slots)
        if key:
            grid.attach(label('Ammo' if key == 'Ammo' else 'Amount', 'key'), 0, row, 1, 1)
            amount = Gtk.Box(spacing=8)
            amount.append(w.spin(entry[key]['value'], 0, 999, lambda v: self.set_amount(entry, key, v)))
            amount.append(label('%d for each slot' % run.default_amount(game, path), 'dim'))
            grid.attach(amount, 1, row, 1, 1)
        box.append(grid)
        box.append(self.attributes_box(entry))
        if run.MODS in entry:
            box.append(self.mods_box(slots, entry))
        remove = w.button('Remove', lambda: self.remove_item(slots, entry), 'danger')
        remove.set_halign(Gtk.Align.START)
        box.append(remove)

    def card(self, path: str, name: str, kind: str, tier: int, width: int, height: int) -> Gtk.Box:
        """The head of the panel: the icon, the name, the kind, the tier and the description."""
        from .window import label

        w = self.window
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class('card')
        if tier:
            card.add_css_class('tier-%d' % tier)
        head = Gtk.Box(spacing=10)
        icon = w.icon(path, width, height)
        if icon:
            head.append(icon)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        title = label(name, 'name', wrap=True)
        title.set_max_width_chars(24)
        title.set_tooltip_text(short_name(path))
        names.append(title)
        names.append(label(kind, 'dim'))
        if tier:
            names.append(label('TIER %d' % tier, 'tag'))
        head.append(names)
        card.append(head)
        description = w.game.equipment.get(path, {}).get('description')
        if description:
            text = label(description, 'description', wrap=True)
            text.set_max_width_chars(40)
            card.append(text)
        return card

    def perks(self) -> dict[str, float]:
        """The values of the perks that the attributes of items use: the pilot's, or the
        hardcore run's own."""
        player = self.window.perk_props()
        if player is None:
            return {}
        out = {}
        for perk in attributes.PERK_GETTERS.values():
            value = profile.perk_value(player, self.window.game, perk)
            if value is not None:
                out[perk] = value
        return out

    def attributes_box(self, entry: Properties) -> Gtk.Box:
        """The attributes of an item with its mods, as the game's equipment screen shows them."""
        from .window import label

        w = self.window
        path = entry['Class']['value']
        rows, failed = attributes.rows(
            w.game,
            path,
            run.mods(entry),
            list(entry[run.SEEDS]['value']) if run.SEEDS in entry else [],
            self.perks(),
            run.ship(self.props),
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        if not rows:
            return box
        box.append(label('ATTRIBUTES', 'section-title'))
        grid = Gtk.Grid(column_spacing=16, row_spacing=3)
        grid.add_css_class('attributes')
        for n, row in enumerate(rows):
            name = label(row.name, 'attr-name')
            name.set_valign(Gtk.Align.START)
            name.set_hexpand(True)
            grid.attach(name, 0, n, 1, 1)
            value = label(row.text, 'attr-value' + (' ' + row.state if row.state else ''), xalign=1.0)
            value.set_justify(Gtk.Justification.RIGHT)
            grid.attach(value, 1, n, 1, 1)
        box.append(grid)
        for mod in failed:
            box.append(label('The editor cannot calculate what %s does.' % w.game.name(mod), 'warning', wrap=True))
        return box

    def mods_box(self, slots: Slots, entry: Properties) -> Gtk.Box:
        from .window import label

        w = self.window
        game = w.game
        mod_limit = self.limits(slots)[1]
        installed = run.mods(entry)
        seeds = list(entry[run.SEEDS]['value']) if run.SEEDS in entry else []
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(label('MODS  (%d OF %d)' % (len(installed), mod_limit), 'section-title'))
        for index, mod in enumerate(installed):
            chip = Gtk.Box(spacing=6)
            chip.add_css_class('chip')
            icon = w.icon(mod, 26, 18)
            if icon:
                chip.append(icon)
            names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
            names.append(label(game.name(mod)))
            effects = attributes.mod_rows(game, mod, seeds[index] if index < len(seeds) else 0)
            if effects:
                text = '   '.join('%s %s' % (r.name, r.text) for r in effects)
                names.append(label(text, 'mod-effect', wrap=True))
            chip.append(names)
            remove = Gtk.Button(icon_name='window-close-symbolic', tooltip_text='Remove this mod')
            remove.add_css_class('flat')
            remove.connect('clicked', lambda _b, i=index: self.remove_mod(entry, i))
            chip.append(remove)
            box.append(chip)
        fitting = game.mods_for(entry['Class']['value'])
        if fitting and len(installed) < mod_limit:
            chosen = [fitting[0]]
            add = Gtk.Box(spacing=8)
            add.append(
                w.dropdown(fitting, [game.name(m) for m in fitting], fitting[0], lambda m: chosen.__setitem__(0, m))
            )
            add.append(w.button('Add mod', lambda: self.add_mod(entry, chosen[0])))
            box.append(add)
        elif not fitting and not installed:
            box.append(label('No mods fit this item.', 'dim'))
        return box

    def names(self, paths: list[str]) -> list[str]:
        game = self.window.game
        out = []
        for path in paths:
            tier = game.equipment.get(path, {}).get('tier')
            out.append('%s%s' % (game.name(path), '  (tier %d)' % tier if tier else ''))
        return out

    # ---- changes

    def add_item(self, slots: Slots, index: int, path: str) -> None:
        run.put_item(self.props, slots, index, path, run.default_amount(self.window.game, path))
        if not slots.keeps_empty:
            index = len(run.items(self.props, slots)) - 1  # a weapon goes at the end of its list
        self.selection = (slots.kind, index)
        self.changed(refresh=True)

    def remove_item(self, slots: Slots, entry: Properties) -> None:
        run.remove_item(self.props, slots, entry)
        self.changed(refresh=True)

    def replace_item(self, entry: Properties, path: str) -> None:
        run.replace_item(entry, path, self.window.game)
        self.changed(refresh=True)

    def set_amount(self, entry: Properties, key: str, value: int) -> None:
        entry[key]['value'] = value
        tile = self.tiles.get(self.selection) if self.selection else None
        if tile:
            tile.corner.set_label(str(value))
            tile.corner.set_visible(True)
        self.changed()

    def set_resource(self, path: str, amount: int) -> None:
        run.set_resource(self.props, path, amount)
        tile = self.tiles.get((RESOURCE, path))
        if tile:
            tile.set_amount(amount)
        self.mark_limit(amount)
        self.changed()

    def add_mod(self, entry: Properties, path: str) -> None:
        run.add_mod(entry, path)
        self.changed(refresh=True)

    def remove_mod(self, entry: Properties, index: int) -> None:
        run.remove_mod(entry, index)
        self.changed(refresh=True)


def clear_box(box: Gtk.Box) -> None:
    from .window import clear

    clear(box)
