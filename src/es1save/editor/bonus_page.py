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

"""The bonus gear of a run that has not started: the items of the offer that the pilot chose,
as slots, and the resources, as one tile for each. It uses the tiles and the panel of the
loadout page."""

from collections.abc import Callable

from .. import run
from ..savegame import Properties
from .gtk import Gtk
from .loadout_page import RESOURCE, LoadoutPage, Tile, clear_box

GEAR = 'Gear'


class BonusPage(LoadoutPage):
    def item_limit(self) -> int | None:
        return run.bonus_item_limit(self.window.perk_props(), self.window.game)

    # ---- the page

    def show(self) -> None:
        from .window import label

        w = self.window
        game = w.game
        clear_box(w.page)
        w.page.append(label('BONUS GEAR', 'page-title'))
        w.page.append(
            label(
                'The gear that the run starts with: the offer that the pilot chose on the Bonus Gear '
                'screen, then random resources. The game reads it only for a run that has not '
                'started yet.',
                'dim',
                wrap=True,
            )
        )
        self.tiles = {}
        limit = self.item_limit()
        items = run.bonus_items(self.props, game)
        w.page.append(label('ITEMS', 'section-title'))
        if limit is not None:
            w.page.append(
                label(
                    'At its level, the Bonus gear perk gives an offer of %d %s. An entry can be an item '
                    'or a resource.' % (limit, 'entry' if limit == 1 else 'entries'),
                    'dim',
                    wrap=True,
                )
            )
        row = Gtk.Box(spacing=6)
        for index in range(max(run.GEAR_SLOTS, len(items))):
            tile = Tile(self, (GEAR, index))
            extra = limit is not None and index >= limit
            if index < len(items):
                entry = items[index]
                path = entry['PickupClass']['value']
                tier = game.equipment.get(path, {}).get('tier', 0)
                amount = int(entry['Amount']['value'])
                tile.show_item(w.icons.item(game, path), game.name(path), tier, 0, str(amount) if amount != 1 else '')
                tile.set_tooltip_text(game.name(path) + ('\nTier %d' % tier if tier else ''))
                if extra:
                    tile.add_css_class('extra')
            else:
                tile.show_empty(extra)
                tile.set_tooltip_text('Empty slot: click to add an item')
            self.tiles[tile.key] = tile
            row.append(tile)
        w.page.append(row)
        w.page.append(label('RESOURCES', 'section-title'))
        w.page.append(self.resource_tiles(run.bonus_resources(self.props, game)))
        if self.selection not in self.tiles:
            self.selection = None
        self.mark_selection()
        self.build_detail()
        w.detail_scroll.set_visible(True)

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
                self.bonus_resource_detail(box, where)
                return
            items = run.bonus_items(self.props, w.game)
            index = int(where)
            if index < len(items):
                self.bonus_item_detail(box, items[index])
            else:
                self.bonus_empty_detail(box, index)

    def bonus_resource_detail(self, box: Gtk.Box, path: str) -> None:
        from .window import label

        w = self.window
        amount = dict(run.bonus_resources(self.props, w.game)).get(path, 0)
        box.append(self.card(path, w.game.name(path), 'Resource', 0, 60, 60))
        row = Gtk.Box(spacing=10)
        row.append(label('Amount', 'key'))
        row.append(w.spin(amount, 0, 99999, lambda v: self.set_bonus_resource(path, v)))
        box.append(row)

    def bonus_empty_detail(self, box: Gtk.Box, index: int) -> None:
        from .window import label

        w = self.window
        box.append(label('EMPTY SLOT', 'section-title'))
        box.append(label('Bonus item %d' % (index + 1), 'dim'))
        offered = run.bonus_item_choices(w.game)
        if not offered:
            box.append(label("The game's data is not available, so the editor cannot offer items.", 'warning'))
            return
        chosen = [offered[0]]
        box.append(self.item_choice(offered, offered[0], lambda p: chosen.__setitem__(0, p)))
        add = w.button('Add', lambda: self.put_bonus_item(index, chosen[0]))
        add.set_halign(Gtk.Align.START)
        box.append(add)

    def bonus_item_detail(self, box: Gtk.Box, entry: Properties) -> None:
        from .window import label

        w = self.window
        game = w.game
        path = entry['PickupClass']['value']
        index = next(n for n, e in enumerate(run.bonus_items(self.props, game)) if e is entry)
        info = game.equipment.get(path, {})
        box.append(self.card(path, game.name(path), run.kind_name(game, path), info.get('tier', 0), 104, 72))
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        offered = run.bonus_item_choices(game)
        if offered:
            grid.attach(label('Item', 'key'), 0, 0, 1, 1)
            grid.attach(self.item_choice(offered, path, lambda p: self.put_bonus_item(index, p)), 1, 0, 1, 1)
        grid.attach(label('Amount', 'key'), 0, 1, 1, 1)
        amount = Gtk.Box(spacing=8)
        amount.append(w.spin(entry['Amount']['value'], 1, 999, lambda v: self.set_bonus_amount(entry, v)))
        amount.append(label('%d for each slot' % run.default_amount(game, path), 'dim'))
        grid.attach(amount, 1, 1, 1, 1)
        box.append(grid)
        remove = w.button('Remove', lambda: self.remove_bonus(entry), 'danger')
        remove.set_halign(Gtk.Align.START)
        box.append(remove)

    def item_choice(self, offered: list[str], current: str, on_change: Callable[[str], object]) -> Gtk.DropDown:
        return self.window.dropdown(offered, self.names(offered), current, on_change, search=True)

    # ---- changes

    def put_bonus_item(self, index: int, path: str) -> None:
        game = self.window.game
        run.put_bonus_item(self.props, game, index, path, run.default_amount(game, path))
        self.selection = (GEAR, min(index, len(run.bonus_items(self.props, game)) - 1))
        self.changed(refresh=True)

    def set_bonus_amount(self, entry: Properties, amount: int) -> None:
        entry['Amount']['value'] = amount
        tile = self.tiles.get(self.selection) if self.selection else None
        if tile:
            tile.corner.set_label(str(amount) if amount != 1 else '')
            tile.corner.set_visible(amount != 1)
        self.changed()

    def remove_bonus(self, entry: Properties) -> None:
        run.remove_bonus_entry(self.props, entry)
        self.changed(refresh=True)

    def set_bonus_resource(self, path: str, amount: int) -> None:
        run.set_bonus_resource(self.props, path, amount)
        tile = self.tiles.get((RESOURCE, path))
        if tile:
            tile.set_amount(amount)
        self.window.update_counts()
        self.changed()
