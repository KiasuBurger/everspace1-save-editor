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

"""A GTK 4 editor for Everspace 1 saves (the es1save-editor command).

It needs PyGObject and GTK 4. This module imports them only when the editor starts, so the
rest of the package works without them.
"""

import argparse
import os
import sys
from collections.abc import Sequence

from .. import __version__
from ..gamedata import SHIP_ICONS
from .icons import find_icons

APP_ID = 'de.rockfishgames.es1save.editor'
COPYRIGHT = 'Copyright © 2026 KiasuBurger'
LICENCE = 'Free software under the GNU General Public License, version 3 or later.'
PAGES = (
    'pilot',
    'ships',
    'perks',
    'blueprints',
    'glyphs',
    'run',
    'loadout',
    'bonus',
    'hc-run',
    'hc-loadout',
    'hc-bonus',
    'hc-perks',
)
# the icon of the desktop entry, below the folder of extracted icons. The game has no inventory
# icon, as Everspace 2 has, so the editor uses the icon of the Interceptor.
APP_ICON = SHIP_ICONS[0]
# whether the desktop lists its applications from .desktop files: Windows and macOS do not
DESKTOP_FILES = sys.platform not in ('win32', 'darwin')


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='es1save-editor', description="Edit the pilot and the current run of Everspace 1's saves."
    )
    p.add_argument('--version', action='version', version='%(prog)s ' + __version__)
    p.add_argument(
        'save',
        nargs='?',
        help='a save, or the folder of the saves, to open (default: where the game keeps them)',
    )
    p.add_argument(
        '--game-data',
        metavar='PATH',
        help='game_data.json to use (default: the one in the cache directory, which the '
        'editor builds from the installed game)',
    )
    p.add_argument(
        '--icons',
        metavar='DIR',
        help="folder of the game's icons as PNG files (default: the one in the cache directory, "
        'which the editor extracts from the installed game)',
    )
    p.set_defaults(install_desktop=False)
    if DESKTOP_FILES:
        p.add_argument(
            '--install-desktop',
            action='store_true',
            help="add the editor to the desktop's applications, and exit",
        )
    p.add_argument('--page', choices=PAGES, help=argparse.SUPPRESS)
    p.add_argument('--screenshot', metavar='PNG', help=argparse.SUPPRESS)
    return p


def desktop_entry(command: str, icon: str | None = None) -> str:
    """The text of the editor's .desktop file, which starts the editor. icon is the path of a
    PNG file. Without it, the entry uses the desktop's icon for games."""
    return (
        '\n'.join(
            [
                '[Desktop Entry]',
                'Type=Application',
                'Name=Everspace Save Editor',
                'Comment=Edit the pilot and the current run of an Everspace save',
                'Exec="%s" %s' % (command.replace('\\', '\\\\').replace('"', '\\"'), '%f'),
                'Icon=%s' % (icon or 'applications-games'),
                'Terminal=false',
                'Categories=Game;',
                'StartupWMClass=%s' % APP_ID,
                'StartupNotify=true',
            ]
        )
        + '\n'
    )


def app_icon(icons: str | None = None) -> str | None:
    """The PNG file of the editor's icon in the folder of extracted icons (the given one, or
    else the one in the cache), or None if it is not there."""
    directory = find_icons(icons)
    path = os.path.join(directory, *APP_ICON.split('/')) + '.png' if directory else None
    return path if path and os.path.isfile(path) else None


def editor_command() -> str:
    """The es1save-editor command of this installation, beside the program that runs."""
    return os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'es1save-editor')


def install_desktop(
    command: str | None = None, data_home: str | None = None, icons: str | None = None
) -> tuple[str, str | None]:
    """Writes the .desktop file for this installation. Returns its path and the icon that it
    uses, or None if the icons are not extracted."""
    command = command or editor_command()
    data_home = data_home or os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    target = os.path.join(data_home, 'applications', APP_ID + '.desktop')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    icon = app_icon(icons)
    with open(target, 'w') as f:
        f.write(desktop_entry(command, icon))
    return target, icon


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.install_desktop:
        target, icon = install_desktop(icons=args.icons)
        print('wrote %s' % target)
        if not icon:
            print(
                "no icon: the game's icons are not extracted. Start the editor once, which extracts "
                'them, and then run this again.'
            )
        return 0
    try:
        from .application import EditorApp
    except (ImportError, ValueError) as e:
        print(
            'es1save-editor: GTK 4 and PyGObject are needed to run the editor (%s).\n'
            "Install your distribution's python3-gobject and gtk4 packages and make the\n"
            'environment see them, e.g.: uv venv --system-site-packages --python /usr/bin/python3' % e,
            file=sys.stderr,
        )
        return 2
    app = EditorApp(args.save, args.game_data, args.page, args.screenshot, args.icons)
    return app.run([])


if __name__ == '__main__':
    sys.exit(main())
