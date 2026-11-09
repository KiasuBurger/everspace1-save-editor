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

"""The editor's window.

The sidebar on the left lists the pages of the pilot, of the regular run and of the hardcore
run. The page on show is in
the middle. The window opens and saves the pair of saves, and has the helpers that the pages
make their controls with."""

import contextlib
import os
import threading
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from .. import __version__, run
from ..gamedata import GameData
from ..gamepaths import find_save_dir
from . import APP_ICON, COPYRIGHT, LICENCE, config
from .bonus_page import BonusPage
from .document import Document, Session
from .gtk import Gdk, Gio, GLib, Gtk, Pango
from .icons import IconStore
from .loadout_page import LoadoutPage
from .pilot_pages import PilotPages
from .run_pages import RunPages

HARDCORE = 'hc-'  # the start of the keys of the pages of the hardcore run


def bonus_count(doc: Document) -> int:
    return len(doc.properties.get(run.BONUS_GEAR, {}).get('value', []))


SHORTCUTS = [  # (window action, key, method)
    ('open', '<Control>o', 'choose_file'),
    ('save', '<Control>s', 'save'),
    ('quit', '<Control>q', 'close'),
    ('settings', '<Control>comma', 'show_settings'),
]


def label(
    text: str, css: str | None = None, wrap: bool = False, xalign: float = 0.0, selectable: bool = False
) -> Gtk.Label:
    lab = Gtk.Label(label=text, xalign=xalign)
    if wrap:
        lab.set_wrap(True)
        lab.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lab.set_max_width_chars(80)
    if selectable:
        lab.set_selectable(True)
    for c in (css or '').split():
        lab.add_css_class(c)
    return lab


class Icon(Gtk.Picture):
    """An icon of a fixed size. It scales its texture to fit in width x height pixels. A
    plain Gtk.Picture asks for the size of its texture, and becomes larger."""

    def __init__(self, texture: Gdk.Texture, width: int, height: int) -> None:
        super().__init__(paintable=texture, content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
        self.size = (width, height)
        self.set_valign(Gtk.Align.CENTER)

    def do_measure(self, orientation: Gtk.Orientation, for_size: int) -> tuple[int, int, int, int]:
        n = self.size[0] if orientation == Gtk.Orientation.HORIZONTAL else self.size[1]
        return n, n, -1, -1


def clear(box: Gtk.Box) -> None:
    """Removes all the children of the box. If the keyboard focus is in the box, the window
    loses the focus first, while the focused widget is still complete. Without this, GTK keeps
    the window focus on the removed widget. On Windows, a key press then goes to a widget that
    is not in the window, and GTK 4 can crash."""
    root = box.get_root()
    focus = root.get_focus() if root else None
    if root and focus and focus.is_ancestor(box):
        root.set_focus(None)
    child = box.get_first_child()
    while child:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


def soon(call: Callable[[], object]) -> None:
    """Calls something once the handler that is running has returned.

    Use this when a handler must remove or replace widgets. A widget must not be removed while
    its own handler runs, and this applies also to the page or panel that holds it. Change the
    save at once, and rebuild only the widgets later. Remove the children of a box with
    clear()."""

    def run() -> bool:
        call()
        return False

    GLib.idle_add(run)


def close_on_escape(window: Gtk.Window) -> None:
    """Closes a dialog when the user presses Escape. GTK does this only for its own dialogs."""
    controller = Gtk.ShortcutController()
    controller.add_shortcut(
        Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string('Escape'), action=Gtk.NamedAction.new('window.close'))
    )
    window.add_controller(controller)


def margins(widget: Gtk.Widget, size: int) -> None:
    widget.set_margin_top(size)
    widget.set_margin_bottom(size)
    widget.set_margin_start(size)
    widget.set_margin_end(size)


class EditorWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, game: GameData, icons: IconStore | None = None) -> None:
        super().__init__(application=app, title='Everspace save editor')
        self.game = game
        self.icons = icons or IconStore(None)
        self.session: Session | None = None
        self.busy = False  # set while controls are filled in, to ignore their signals
        self.shown: str | None = None  # the page on show
        self.hardcore_shown = False  # True while a page of the hardcore run is on show
        # the options of the command line that the settings do not change
        self.command_line: set[str] = set()
        self.add_css_class('es1')
        self.set_default_size(1280, 900)

        header = Gtk.HeaderBar()
        self.title_label = label('EVERSPACE SAVE EDITOR', 'title app-title', xalign=0.5)
        self.subtitle_label = label('No saves open', 'subtitle', xalign=0.5)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        titles.append(self.title_label)
        titles.append(self.subtitle_label)
        header.set_title_widget(titles)
        open_button = Gtk.Button(label='Open…')
        open_button.connect('clicked', lambda _b: self.choose_file())
        header.pack_start(open_button)
        self.save_button = Gtk.Button(label='Save', sensitive=False)
        self.save_button.add_css_class('accent')
        self.save_button.add_css_class('suggested-action')
        self.save_button.connect('clicked', lambda _b: self.save())
        menu = Gio.Menu()
        menu.append('Settings', 'win.settings')
        menu.append('About', 'win.about')
        menu_button = Gtk.MenuButton(icon_name='open-menu-symbolic', menu_model=menu, tooltip_text='Menu')
        header.pack_end(menu_button)
        header.pack_end(self.save_button)
        self.set_titlebar(header)

        self.actions = {}
        for name, accel, handler in SHORTCUTS:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _a, _p, h=handler: getattr(self, h)())
            self.add_action(action)
            self.actions[name] = action
            app.set_accels_for_action('win.' + name, [accel])
        self.actions['save'].set_enabled(False)
        open_button.set_tooltip_text('Ctrl+O')
        self.save_button.set_tooltip_text('Ctrl+S')
        about = Gio.SimpleAction.new('about', None)
        about.connect('activate', lambda _a, _p: self.show_about())
        self.add_action(about)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body = Gtk.Box(vexpand=True)
        root.append(body)
        self.status = label('', 'statusbar')
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        root.append(self.status)
        self.set_child(root)

        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.sidebar.add_css_class('sidebar')
        self.sidebar.set_size_request(230, -1)
        side_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        side_scroll.set_child(self.sidebar)
        side_scroll.set_hexpand(False)
        body.append(side_scroll)

        self.page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, hexpand=True)
        margins(self.page, 16)
        self.page_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True)
        self.page_scroll.set_child(self.page)
        body.append(self.page_scroll)

        # the panel of the selected tile, which only the loadout page shows
        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        margins(self.detail, 14)
        self.detail_scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, visible=False, hexpand=False, propagate_natural_width=False
        )
        self.detail_scroll.add_css_class('detail')
        self.detail_scroll.set_size_request(400, -1)
        self.detail_scroll.set_child(self.detail)
        body.append(self.detail_scroll)

        self.pilot_pages = PilotPages(self)
        self.run_pages = RunPages(self)
        self.loadout_page = LoadoutPage(self)
        self.bonus_page = BonusPage(self)
        self.nav_buttons: dict[str, Gtk.ToggleButton] = {}
        self.nav_handlers: dict[str, Callable[..., object]] = {}
        self.connect('close-request', self.on_close_request)
        self.show_welcome()

    # ---- state

    @property
    def open_session(self) -> Session:
        if self.session is None:
            raise RuntimeError('no saves are open')
        return self.session

    @property
    def player(self) -> Document | None:
        return self.session.player if self.session else None

    @property
    def run_doc(self) -> Document | None:
        """The run of the page on show: the hardcore run on its pages, else the regular run."""
        if not self.session:
            return None
        return self.session.hardcore if self.hardcore_shown else self.session.run

    def perk_props(self) -> Any:
        """The tree whose Perks give the run on show its limits: the hardcore run's own perks,
        or the pilot's for a regular run. None if it is not open."""
        doc = self.run_doc
        player = self.session.player_props() if self.session else None
        return run.perk_props(doc.properties if doc else None, player)

    def set_status(self, text: str, error: bool = False) -> None:
        self.status.set_label(text)
        if error:
            self.status.add_css_class('error')
        else:
            self.status.remove_css_class('error')

    def update_title(self) -> None:
        dirty = bool(self.session and self.session.dirty)
        self.actions['save'].set_enabled(dirty)
        self.save_button.set_sensitive(dirty)
        if not self.session:
            self.subtitle_label.set_label('No saves open')
            return
        changed = ', '.join(d.name for d in self.session.documents if d.dirty)
        self.subtitle_label.set_label(
            '%s%s' % (self.session.folder, '  •  unsaved changes in %s' % changed if changed else '')
        )

    def mark_dirty(self, doc: Document) -> None:
        doc.dirty = True
        self.update_title()

    @contextlib.contextmanager
    def filling(self) -> Iterator[None]:
        """Ignores the signals of the controls filled in meanwhile, which are not changes."""
        self.busy = True
        try:
            yield
        finally:
            self.busy = False

    # ---- opening and saving

    def show_welcome(self) -> None:
        self.detail_scroll.set_visible(False)
        clear(self.page)
        clear(self.sidebar)
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
            vexpand=True,
        )
        box.add_css_class('welcome')
        box.append(label('EVERSPACE SAVE EDITOR', 'big', xalign=0.5))
        box.append(label('Version %s' % __version__, 'dim', xalign=0.5, selectable=True))
        button = Gtk.Button(label='Open the saves…', halign=Gtk.Align.CENTER)
        button.add_css_class('accent')
        button.add_css_class('suggested-action')
        button.connect('clicked', lambda _b: self.choose_file())
        box.append(button)
        about = label('%s\n%s' % (COPYRIGHT, LICENCE), 'dim small', xalign=0.5)
        about.set_justify(Gtk.Justification.CENTER)
        box.append(about)
        self.page.append(box)

    def start_folder(self) -> str | None:
        """Where the Open dialog starts: the folder chosen for it in the settings, or else the
        folder of the open saves, or else the folder of the saves last opened, or else the
        folder where the game keeps its saves."""
        for folder in (
            config.load().get('open_directory'),
            self.session.folder if self.session else None,
            config.load().get('save_directory'),
        ):
            if isinstance(folder, str) and os.path.isdir(folder):
                return folder
        return find_save_dir()

    def choose_file(self) -> None:
        dialog = Gtk.FileDialog(title='Open an Everspace save')
        folder = self.start_folder()
        if folder:
            dialog.set_initial_folder(Gio.File.new_for_path(folder))
        saves = Gtk.FileFilter()
        saves.set_name('Everspace saves')
        saves.add_pattern('*.sav')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(saves)
        dialog.set_filters(filters)

        def done(dlg: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                file = dlg.open_finish(result)
            except GLib.Error:
                return
            self.confirm_discard(lambda: self.open_path(file.get_path()))

        dialog.open(self, None, done)

    def open_path(self, path: str, then: Callable[[], object] | None = None, remember: bool = True) -> None:
        self.set_status('Loading %s…' % path)
        self.set_sensitive(False)

        def work() -> None:
            try:
                session = Session.open(path)
                error = None
            except Exception as e:  # noqa: BLE001 (the window shows the error. A bad file must not close the window.)
                session, error = None, e
            GLib.idle_add(finish, session, error)

        def finish(session: Session | None, error: Exception | None) -> bool:
            self.set_sensitive(True)
            if error or session is None:
                self.set_status('Could not open %s: %s' % (path, error), error=True)
            else:
                self.session = session
                self.build_sidebar()
                self.show_page('pilot' if session.player else 'run' if session.run else HARDCORE + 'run')
                self.update_title()
                self.set_status('Opened %s' % ', '.join(d.path for d in session.documents))
                if remember:
                    config.update(save_directory=session.folder)
                if then:
                    then()
            return False

        threading.Thread(target=work, daemon=True).start()

    def save(self, then: Callable[[], object] | None = None) -> None:
        session = self.open_session
        if not session.dirty:
            return
        self.set_status('Saving…')
        self.set_sensitive(False)

        def work() -> None:
            try:
                kept = session.write(config.backup_directory(), config.backups_kept(), config.backups())
                error = None
            except Exception as e:  # noqa: BLE001 (shown to the user)
                kept, error = [], e
            GLib.idle_add(finish, kept, error)

        def finish(kept: list[str], error: Exception | None) -> bool:
            self.set_sensitive(True)
            if error:
                self.set_status('Saving failed: %s' % error, error=True)
            else:
                self.update_title()
                self.set_status('Saved%s' % ('  (the previous files are kept as %s)' % ', '.join(kept) if kept else ''))
                if then:
                    then()
            return False

        threading.Thread(target=work, daemon=True).start()

    def confirm(self, message: str, detail: str, verb: str, proceed: Callable[[], object]) -> None:
        """Asks before doing something that cannot be undone. Cancel is the default."""
        dialog = Gtk.AlertDialog(message=message, detail=detail, buttons=['Cancel', verb])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)

        def done(dlg: Gtk.AlertDialog, result: Gio.AsyncResult) -> None:
            try:
                if dlg.choose_finish(result) == 1:
                    proceed()
            except GLib.Error:
                pass

        dialog.choose(self, None, done)

    def confirm_discard(self, proceed: Callable[[], object]) -> None:
        if not self.session or not self.session.dirty:
            proceed()
            return
        self.confirm('Discard unsaved changes?', 'The open saves have changes that are not saved.', 'Discard', proceed)

    def on_close_request(self, _window: Gtk.Window) -> bool:
        if self.session and self.session.dirty:

            def close() -> None:
                for doc in self.open_session.documents:
                    doc.dirty = False
                self.close()

            self.confirm_discard(close)
            return True
        return False

    # ---- the menu

    def show_settings(self) -> None:
        from .settings import SettingsDialog

        SettingsDialog(self).present()

    def reread_game(self) -> None:
        app = self.get_application()
        prepare = getattr(app, 'prepare_game_data', None)
        if prepare:
            prepare(self, force=True)

    def show_icon(self) -> bool:
        """Gives the window the icon of the editor, for the taskbar and the list of windows. This
        needs the extracted icons and a window on the screen. Returns whether the window got the
        icon. The desktop decides if it shows the icon: X11 and Windows show it. On Wayland, most
        compositors use the icon of the installed desktop file."""
        surface = self.get_surface()
        texture = self.icons.texture(APP_ICON)
        if not surface or not texture:
            return False
        surface.set_icon_list([texture])
        return True

    def show_about(self) -> None:
        about = Gtk.AboutDialog(
            transient_for=self,
            modal=True,
            program_name='Everspace Save Editor',
            version=__version__,
            copyright=COPYRIGHT,
            license_type=Gtk.License.GPL_3_0,
        )
        # the icon of the editor, as the desktop file has it. Without the extracted icons, the
        # dialog has no logo.
        texture = self.icons.texture(APP_ICON)
        if texture:
            about.set_logo(texture)
        about.add_css_class('es1')
        about.present()

    # ---- navigation

    def redraw(self) -> None:
        """Draws the open saves again on the page on show, after the game's data changed."""
        self.show_icon()  # the icons can be new
        if not self.session:
            return
        shown = self.shown
        self.build_sidebar()
        self.show_page(shown or 'pilot')

    def build_sidebar(self) -> None:
        clear(self.sidebar)
        self.nav_buttons = {}
        self.nav_handlers = {}
        group: Gtk.ToggleButton | None = None

        def add(key: str, text: str, handler: Callable[..., object], count: int | None = None) -> None:
            nonlocal group
            button = Gtk.ToggleButton()
            button.add_css_class('nav')
            row = Gtk.Box(spacing=6)
            row.append(label(text))
            if count is not None:
                c = label(str(count), 'count', xalign=1.0)
                c.set_hexpand(True)
                row.append(c)
            button.set_child(row)
            if group:
                button.set_group(group)
            group = group or button
            button.connect('clicked', self.on_nav_clicked, key)
            self.sidebar.append(button)
            self.nav_buttons[key] = button
            self.nav_handlers[key] = handler

        if self.player:
            p = self.pilot_pages
            self.sidebar.append(label('PILOT', 'heading'))
            add('pilot', 'Pilot', p.show_pilot)
            add('ships', 'Ships', p.show_ships)
            add('perks', 'Perks', p.show_perks)
            add('blueprints', 'Blueprints', p.show_blueprints)
            add('glyphs', 'Glyphs and enhancements', p.show_glyphs)
        session = self.open_session
        for prefix, heading, doc in (('', 'CURRENT RUN', session.run), (HARDCORE, 'HARDCORE RUN', session.hardcore)):
            if not doc:
                continue
            r = self.run_pages
            self.sidebar.append(label(heading, 'heading'))
            add(prefix + 'run', 'Run', r.show_run)
            if run.started(doc.properties):
                add(prefix + 'loadout', 'Loadout', self.loadout_page.show, self.equipped_count(doc))
            add(prefix + 'bonus', 'Bonus gear', self.bonus_page.show, bonus_count(doc))
            if prefix:
                add(prefix + 'perks', 'Perks', self.pilot_pages.show_hardcore_perks)

    def on_nav_clicked(self, button: Gtk.ToggleButton, key: str) -> None:
        if button.get_active() and not self.busy:
            self.show_page(key)

    def update_counts(self) -> None:
        """Brings the item counts in the sidebar up to date."""
        doc = self.run_doc
        if not doc:
            return
        prefix = HARDCORE if self.hardcore_shown else ''
        counts = {prefix + 'loadout': self.equipped_count(doc), prefix + 'bonus': bonus_count(doc)}
        for key, n in counts.items():
            button = self.nav_buttons.get(key)
            row = button.get_child() if button else None
            count = row.get_last_child() if isinstance(row, Gtk.Box) else None
            if isinstance(count, Gtk.Label) and count.has_css_class('count'):
                count.set_label(str(n))

    def equipped_count(self, doc: Document) -> int:
        """The number of weapons, devices and consumables of the ship of a run."""
        return sum(len(run.items(doc.properties, s)) for s in run.SLOTS)

    def show_page(self, key: str) -> None:
        handler = self.nav_handlers.get(key)
        if handler is None:
            return
        if key != self.shown:
            self.loadout_page.selection = None
            self.bonus_page.selection = None
        self.detail_scroll.set_visible(False)
        self.shown = key
        self.hardcore_shown = key.startswith(HARDCORE)
        button = self.nav_buttons[key]
        if not button.get_active():
            with self.filling():
                button.set_active(True)
        handler()

    def refresh(self) -> None:
        """Draws the page on show again, keeping where it is scrolled to."""
        adjustment = self.page_scroll.get_vadjustment()
        position = adjustment.get_value()
        if self.shown:
            self.nav_handlers[self.shown]()
        GLib.idle_add(lambda: adjustment.set_value(position) and False)

    def refresh_soon(self) -> None:
        """Draws the page on show again after the handler that is running returns. The control
        that changed is on the page or its panel, and it must not be removed in its own handler."""
        soon(self.refresh)

    def start_page(self, title: str, note: str = '') -> None:
        clear(self.page)
        self.page.append(label(title, 'page-title'))
        if note:
            self.page.append(label(note, 'dim', wrap=True))

    # ---- controls

    def dropdown(
        self,
        values: Sequence[Any],
        names: Sequence[str],
        current: Any,
        on_change: Callable[..., object],
        search: bool = False,
    ) -> Gtk.DropDown:
        """A choice of `names`, which stand for `values`. A current value that is not one of
        them is put first."""
        values, names = list(values), list(names)
        if current not in values:
            values.insert(0, current)
            names.insert(0, str(current))
        dd = Gtk.DropDown.new_from_strings(names)
        if search:
            dd.set_enable_search(True)
            dd.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, 'string'))
            dd.set_search_match_mode(Gtk.StringFilterMatchMode.SUBSTRING)
        dd.set_selected(values.index(current))

        def changed(d: Gtk.DropDown, _p: object) -> None:
            if not self.busy:
                on_change(values[d.get_selected()])

        dd.connect('notify::selected', changed)
        return dd

    def spin(
        self,
        value: float,
        low: float,
        high: float,
        on_change: Callable[..., object],
        digits: int = 0,
        step: float = 1,
    ) -> Gtk.SpinButton:
        sb = Gtk.SpinButton.new_with_range(low, high, step)
        sb.set_digits(digits)
        sb.set_value(value)

        def changed(s: Gtk.SpinButton) -> None:
            if not self.busy:
                on_change(s.get_value() if digits else round(s.get_value()))

        sb.connect('value-changed', changed)
        return sb

    def switch(self, active: bool, on_change: Callable[..., object]) -> Gtk.Switch:
        sw = Gtk.Switch()
        sw.set_active(active)
        sw.set_halign(Gtk.Align.START)
        sw.set_valign(Gtk.Align.CENTER)

        def changed(s: Gtk.Switch, _p: object) -> None:
            if not self.busy:
                on_change(s.get_active())

        sw.connect('notify::active', changed)
        return sw

    def check(self, text: str, active: bool, on_change: Callable[..., object]) -> Gtk.CheckButton:
        cb = Gtk.CheckButton(label=text, active=active)

        def toggled(c: Gtk.CheckButton) -> None:
            if not self.busy:
                on_change(c.get_active())

        cb.connect('toggled', toggled)
        return cb

    def icon(self, path: str, width: int, height: int) -> Icon | None:
        """The icon of an item or resource, scaled to fit in width x height pixels, or None if
        there is no icon for it."""
        return self.icon_named(self.game.icon(path), width, height)

    def icon_named(self, name: str | None, width: int, height: int) -> Icon | None:
        """An icon by its texture path in the game data (of a perk or a glyph, for example),
        scaled to fit in width x height pixels. None if there is no such icon."""
        texture = self.icons.texture(name)
        return Icon(texture, width, height) if texture else None

    def button(self, text: str, on_click: Callable[..., object], css: str | None = None) -> Gtk.Button:
        b = Gtk.Button(label=text)
        b.set_halign(Gtk.Align.START)
        b.set_valign(Gtk.Align.CENTER)
        if css:
            b.add_css_class(css)
        b.connect('clicked', lambda _b: on_click())
        return b
