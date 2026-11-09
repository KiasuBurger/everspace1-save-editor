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

"""The settings dialog: where the game is, where saves are opened from and backed up to, and
how the editor looks. A change takes effect when the user makes it. config.py keeps it in its
file."""

import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from .. import gamepaths
from . import DESKTOP_FILES, config, editor_command, install_desktop
from .application import find_game
from .document import default_backup_dir
from .gtk import Gio, GLib, Gtk, Pango
from .window import clear, close_on_escape, label, margins, soon

if TYPE_CHECKING:
    from .window import EditorWindow

PAGES = (('game', 'Game'), ('saves', 'Saves'), ('appearance', 'Appearance'))
KEPT = (None, 5, 10, 20, 50)  # the choices of how many backups of each file to keep
THEMES = (('game', 'Everspace-esque'), ('system', 'System Theme'))


class SettingsDialog(Gtk.Window):
    def __init__(self, window: EditorWindow) -> None:
        super().__init__(transient_for=window, modal=True, title='Settings', resizable=False)
        self.add_css_class('es1')
        self.add_css_class('settings')
        close_on_escape(self)
        self.window = window
        self.set_default_size(620, -1)
        self.stack = Gtk.Stack()
        self.pages = {}
        for name, title in PAGES:
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            margins(page, 18)
            self.pages[name] = page
            self.stack.add_titled(page, name, title)
        switcher = Gtk.StackSwitcher(stack=self.stack, halign=Gtk.Align.CENTER)
        switcher.set_margin_top(12)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(switcher)
        box.append(self.stack)
        self.set_child(box)
        self.fill()

    def fill(self) -> None:
        """Draws the pages from the settings as they are now."""
        for page in self.pages.values():
            clear(page)
        self.fill_game(self.pages['game'])
        self.fill_saves(self.pages['saves'])
        self.fill_appearance(self.pages['appearance'])

    # ---- the pages

    def fill_game(self, page: Gtk.Box) -> None:
        chosen = config.load().get('game_directory')
        game = find_game()
        page.append(label('GAME FOLDER', 'section-title'))
        page.append(folder_label(game or 'Not found'))
        if game and isinstance(chosen, str) and game == gamepaths.game_root(chosen):
            note = 'Manually selected'
        elif game:
            note = 'Autodetected'
        else:
            note = 'Unable to detect game folder'
        page.append(label(note, 'dim', wrap=True))
        page.append(button_row(('Choose…', self.choose_game), ('Detect', self.detect_game)))

        page.append(label('GAME DATA CACHE', 'section-title'))
        page.append(
            label(
                'The item names, perks, glyphs and icons come from the game files. After an update of '
                'the game, rebuild the cache to get the latest version.',
                'dim',
                wrap=True,
            )
        )
        flags = sorted({'--game-data', '--icons'} & self.window.command_line)
        read = button('Rebuild cache', self.read_again)
        read.set_sensitive(bool(game) and not flags)
        page.append(button_row(read))
        if flags:
            page.append(label('The editor was started with %s instead.' % ' and '.join(flags), 'dim', wrap=True))
        page.append(label('CACHE LOCATION', 'section-title'))
        cache = gamepaths.cache_dir()
        page.append(folder_label(cache))
        page.append(button_row(('Open folder', lambda: self.open_folder(cache))))

    def fill_saves(self, page: Gtk.Box) -> None:
        settings = config.load()
        page.append(label('OPENING SAVES', 'section-title'))
        fixed = settings.get('open_directory')
        fixed = fixed if isinstance(fixed, str) else None
        where = Gtk.DropDown.new_from_strings(['Last Used Folder', 'Selected Folder'])
        where.set_selected(1 if fixed else 0)
        where.connect('notify::selected', lambda d, _p: self.set_open_mode(d.get_selected() == 1))
        page.append(row('Open Dialog Location', where))
        if fixed:
            page.append(folder_label(fixed))
            saves = gamepaths.find_save_dir()
            game_saves = button('Detect Game Saves', lambda: self.change(open_directory=saves))
            game_saves.set_sensitive(bool(saves) and saves != fixed)
            page.append(button_row(('Choose…', lambda: self.choose_folder('open_directory', fixed)), game_saves))

        page.append(label('BACKUPS', 'section-title'))
        enabled = Gtk.Switch(active=config.backups(), halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
        enabled.connect('notify::active', lambda s, _p: self.change(backups=None if s.get_active() else False))
        page.append(row('Back up a save before replacing it', enabled))
        if not config.backups():
            return
        page.append(label('The editor puts the backup copies in this folder.', 'dim', wrap=True))
        folder = config.backup_directory()
        page.append(folder_label(folder))
        default = button('Default folder', lambda: self.change(backup_directory=None))
        default.set_sensitive(folder != default_backup_dir())
        page.append(
            button_row(
                ('Choose…', lambda: self.choose_folder('backup_directory', folder)),
                ('Open folder', lambda: self.open_folder(folder)),
                default,
            )
        )
        kept = config.backups_kept()
        keep = Gtk.DropDown.new_from_strings(['Every copy'] + ['The newest %d' % n for n in KEPT[1:]])
        keep.set_selected(KEPT.index(kept) if kept in KEPT else 0)
        keep.connect('notify::selected', lambda d, _p: self.change(backups_kept=KEPT[d.get_selected()]))
        page.append(row('Number of backups to keep for each save', keep))

    def fill_appearance(self, page: Gtk.Box) -> None:
        page.append(label('COLOURS', 'section-title'))
        theme = config.load().get('theme')
        names = [name for name, _ in THEMES]
        colours = Gtk.DropDown.new_from_strings([title for _, title in THEMES])
        colours.set_selected(names.index(theme) if theme in names else 0)
        colours.connect('notify::selected', lambda d, _p: self.set_theme(names[d.get_selected()]))
        page.append(row('Theme', colours))

        if DESKTOP_FILES:
            page.append(label('APPLICATIONS MENU', 'section-title'))
            page.append(
                label(
                    'Create a desktop file for the editor. This adds the editor to the applications menu of '
                    'most desktops. GNOME Shell needs it to show the icon of the window.',
                    'dim',
                    wrap=True,
                )
            )
            add = button('Create desktop file', self.add_to_menu)
            if not os.path.exists(editor_command()):
                add.set_sensitive(False)
                add.set_tooltip_text('The editor can add only the es1save-editor command')
            page.append(button_row(add))
            self.menu_note = label('', 'dim', wrap=True)
            page.append(self.menu_note)

    # ---- what the controls do

    def change(self, **values: object) -> None:
        config.update(**values)
        # the control that changed is on the pages, which must not be drawn again in its handler
        soon(self.fill)

    def set_theme(self, theme: str) -> None:
        from .application import apply_theme

        self.change(theme=None if theme == 'game' else theme)
        apply_theme()

    def set_open_mode(self, fixed: bool) -> None:
        if not fixed:
            self.change(open_directory=None)
        elif not isinstance(config.load().get('open_directory'), str):
            start = self.window.start_folder() or os.path.expanduser('~')
            self.change(open_directory=start)

    def choose_folder(self, key: str, current: str) -> None:
        dialog = Gtk.FileDialog(title='Choose a folder')
        if os.path.isdir(current):
            dialog.set_initial_folder(Gio.File.new_for_path(current))

        def done(dlg: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                path = dlg.select_folder_finish(result).get_path()
            except GLib.Error:
                return
            if path:
                self.change(**{key: path})

        dialog.select_folder(self, None, done)

    def choose_game(self) -> None:
        dialog = Gtk.FileDialog(title='Choose the folder Everspace is installed in')

        def done(dlg: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                path = dlg.select_folder_finish(result).get_path()
            except GLib.Error:
                return
            game = gamepaths.game_root(path) if path else None
            if game:
                self.change(game_directory=game)
            else:
                Gtk.AlertDialog(
                    message='That is not Everspace',
                    detail='%s is not an Everspace installation, and is not in one.' % path,
                ).show(self)

        dialog.select_folder(self, None, done)

    def detect_game(self) -> None:
        """Looks for the game where Steam and GOG put it, as the editor does when no folder is
        chosen. If it finds the game, the editor uses that folder from then on."""
        if gamepaths.find_game():
            self.change(game_directory=None)
            return
        chosen = config.load().get('game_directory')
        Gtk.AlertDialog(
            message='Everspace was not found',
            detail='It is not in a place where Steam or GOG put it.%s'
            % (' The editor keeps the folder that you chose.' if isinstance(chosen, str) else ''),
        ).show(self)

    def read_again(self) -> None:
        self.close()  # the status bar of the window shows the progress
        self.window.reread_game()

    def open_folder(self, folder: str) -> None:
        try:
            os.makedirs(folder, exist_ok=True)  # the first save makes the backup folder
        except OSError as e:
            self.window.set_status('Could not open %s: %s' % (folder, e), error=True)
            return

        def done(launcher: Gtk.FileLauncher, result: Gio.AsyncResult) -> None:
            try:
                launcher.launch_finish(result)
            except GLib.Error as e:
                self.window.set_status('Could not open %s: %s' % (folder, e.message), error=True)

        Gtk.FileLauncher.new(Gio.File.new_for_path(folder)).launch(self, None, done)

    def add_to_menu(self) -> None:
        try:
            target, icon = install_desktop(icons=self.window.icons.directory)
        except OSError as e:
            self.menu_note.set_label('Could not add it: %s' % e)
            return
        self.menu_note.set_label(
            'Added as %s.' % target
            if icon
            else "Added as %s, without an icon: the editor did not read the game's icons yet." % target
        )


def folder_label(path: str) -> Gtk.Label:
    lab = label(path, 'folder', selectable=True)
    lab.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
    lab.set_tooltip_text(path)
    return lab


def button(text: str, handler: Callable[[], object]) -> Gtk.Button:
    b = Gtk.Button(label=text)
    b.connect('clicked', lambda _b: handler())
    return b


def button_row(*buttons: Gtk.Button | tuple[str, Callable[[], object]]) -> Gtk.Box:
    box = Gtk.Box(spacing=8)
    for b in buttons:
        box.append(b if isinstance(b, Gtk.Button) else button(b[0], b[1]))
    return box


def row(title: str, widget: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(spacing=12)
    box.add_css_class('editor-row')
    box.append(label(title, 'field'))
    widget.set_hexpand(True)
    box.append(widget)
    return box
