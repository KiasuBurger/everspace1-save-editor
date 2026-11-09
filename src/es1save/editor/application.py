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

"""The GTK application: its style, the game's data, and the window it opens."""

import os
import sys
import threading

import gi

from .. import gamepaths
from ..gamedata import GameData
from . import APP_ID, config, icons
from .gtk import Gdk, Gio, GLib, Gtk
from .window import EditorWindow


def start_path(path: str | None) -> str | None:
    """The saves to open when the editor starts: the path on the command line, or else the
    folder where the game keeps its saves. The editor opens the folder last opened only when it
    cannot find the game's folder. Thus it does not open a copy by mistake."""
    return path or gamepaths.find_save_dir() or config.load().get('save_directory')


def stylesheet(system_theme: bool = False) -> str:
    """The editor's CSS: the colours, the game's or the GTK theme's, and then the layout
    that uses them."""
    here = os.path.dirname(os.path.abspath(__file__))
    parts = []
    for name in ('system.css' if system_theme else 'game.css', 'style.css'):
        with open(os.path.join(here, name)) as f:
            parts.append(f.read())
    return '\n'.join(parts)


def use_libadwaita() -> bool:
    """Draws the application with libadwaita if it is installed, as nearly every GTK 4
    program on a desktop is. Without it GTK draws its own version of the theme, which is
    close but not the same."""
    try:
        gi.require_version('Adw', '1')
        from gi.repository import Adw
    except ImportError, ValueError:
        return False
    Adw.init()
    return True


def windows_prefers_dark() -> bool:
    """Whether Windows draws applications dark. GTK does not look, and draws light unless told."""
    if sys.platform != 'win32':
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
        ) as key:
            return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
    except OSError:
        return False


adwaita = False
provider: Gtk.CssProvider | None = None


def apply_theme() -> None:
    """Draws every window in the theme the settings name: the game's colours, always dark, or
    the desktop's theme. It can be called again at any time."""
    global provider
    system_theme = config.load().get('theme') == 'system'
    settings = Gtk.Settings.get_default()
    if adwaita:
        from gi.repository import Adw

        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.DEFAULT if system_theme else Adw.ColorScheme.FORCE_DARK
        )
    elif settings:
        settings.set_property('gtk-application-prefer-dark-theme', not system_theme or windows_prefers_dark())
    if provider is None:
        provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    provider.load_from_string(stylesheet(system_theme))


def find_game() -> str | None:
    """The game's installation: the one chosen in the settings, or else one found."""
    chosen = config.load().get('game_directory')
    if isinstance(chosen, str) and gamepaths.game_root(chosen):
        return gamepaths.game_root(chosen)
    return gamepaths.find_game()


class EditorApp(Gtk.Application):
    def __init__(
        self,
        path: str | None = None,
        game_data: str | None = None,
        page: str | None = None,
        screenshot: str | None = None,
        icons_dir: str | None = None,
    ) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.path = path
        self.game_data = game_data
        self.page = page
        self.screenshot = screenshot
        self.icons_dir = icons_dir

    def do_activate(self) -> None:
        global adwaita
        adwaita = use_libadwaita()
        apply_theme()
        game = GameData.load(self.game_data)
        window = EditorWindow(self, game, icons.IconStore(icons.find_icons(self.icons_dir)))
        window.command_line = {
            option for option, given in (('--game-data', self.game_data), ('--icons', self.icons_dir)) if given
        }
        window.present()
        path = start_path(self.path)

        def then() -> None:
            window.show_icon()
            if path and os.path.exists(path):
                # a screenshot must not change the folder that the editor remembers
                window.open_path(path, then=self.after_open, remember=not self.screenshot)

        if self.game_data:
            then()
        else:
            self.prepare_game_data(window, then)

    def prepare_game_data(self, window: EditorWindow, then: object = None, force: bool = False) -> None:
        """Reads the game's data and its icons into the cache, in the background, and then
        calls `then`. It reads the data only if the cache did not come from the game as it is
        installed now. It reads the icons only if the data changed or the cache does not have
        all of them, and never when --icons names a folder."""
        game_dir = find_game()
        if not game_dir:
            if not window.game:
                window.set_status('The game was not found: names and limits are not available.', error=True)
            if callable(then):
                then()
            return
        build = force or not window.game.is_current(game_dir)
        extract = not self.icons_dir and (build or not window.icons.has_all(window.game.icons()))
        if not build and not extract:
            if callable(then):
                then()
            return
        window.set_status("Reading the game's data from %s…" % game_dir)

        def work() -> None:
            game, icons_dir, errors = window.game, None, []
            if build:
                try:
                    game = GameData.build(game_dir)
                    game.save()
                except Exception as e:  # noqa: BLE001 (the window shows the error, and the editor works without the data)
                    game = GameData()
                    errors.append("Could not read the game's data: %s" % e)
            if extract and game:
                try:
                    icons.extract(game_dir, game.icons(), icons.cache_dir())
                    icons_dir = icons.cache_dir()
                except Exception as e:  # noqa: BLE001 (the window shows the error, and the editor works without icons)
                    errors.append("Could not read the game's icons: %s" % e)
            GLib.idle_add(finish, game if build and game else None, icons_dir, errors)

        def finish(game: GameData | None, icons_dir: str | None, errors: list[str]) -> bool:
            if game is not None:
                window.game = game
            if icons_dir:
                window.icons = icons.IconStore(icons_dir)
            if errors:
                window.set_status(' '.join(errors), error=True)
            else:
                window.set_status("Read the game's files from %s" % game_dir)
            if game is not None or icons_dir:
                window.redraw()
            if callable(then):
                then()
            return False

        threading.Thread(target=work, daemon=True).start()

    def after_open(self) -> None:
        window = self.get_active_window()
        if not isinstance(window, EditorWindow):
            return
        if self.page:
            window.show_page(self.page)
        if self.screenshot:
            GLib.timeout_add(900, self.take_screenshot, window)

    def take_screenshot(self, window: EditorWindow) -> bool:
        """Renders the window to a PNG and quits. It is for checking the layout without a desktop."""
        paintable = Gtk.WidgetPaintable.new(window)
        width, height = window.get_width(), window.get_height()
        snapshot = Gtk.Snapshot()
        paintable.snapshot(snapshot, width, height)
        node = snapshot.to_node()
        texture = window.get_native().get_renderer().render_texture(node, None)
        texture.save_to_png(self.screenshot)
        self.quit()
        return False
