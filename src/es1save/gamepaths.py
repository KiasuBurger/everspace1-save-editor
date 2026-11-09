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

"""Where the game is installed and where it keeps its saves.

The functions look for both in the places where Steam and GOG put them. They read no files.
"""

import os
import sys

GAME_DIRECTORY = 'EVERSPACE'
PAKS = os.path.join('RSG', 'Content', 'Paks')
STEAM_APP = '396750'  # the game on Steam. Its Proton prefix holds the saves when Linux runs the Windows build.
SAVES = os.path.join('RSG', 'Saved', 'SaveGames')


def game_root(path: str) -> str | None:
    """The installation that is at `path`, holds `path`, or is directly in `path`. None if there is no such installation."""
    path = os.path.abspath(path)
    candidates = [path, os.path.join(path, GAME_DIRECTORY)]
    while os.path.dirname(path) != path:
        path = os.path.dirname(path)
        candidates.append(path)
    for c in candidates:
        if os.path.isdir(os.path.join(c, PAKS)):
            return c
    return None


def steam_libraries() -> list[str]:
    """The directories that may be Steam libraries: where Steam is installed, and the others
    it lists."""
    home = os.path.expanduser('~')
    roots = [
        os.path.join(home, '.steam', 'steam'),
        os.path.join(home, '.steam', 'root'),
        os.path.join(home, '.local', 'share', 'Steam'),
        os.path.join(home, '.var', 'app', 'com.valvesoftware.Steam', '.local', 'share', 'Steam'),
        os.path.join(home, 'snap', 'steam', 'common', '.local', 'share', 'Steam'),
        os.path.join(home, 'Library', 'Application Support', 'Steam'),
    ]
    if sys.platform == 'win32':
        for variable in ('ProgramFiles(x86)', 'ProgramFiles'):
            if os.environ.get(variable):
                roots.append(os.path.join(os.environ[variable], 'Steam'))
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                roots.insert(0, winreg.QueryValueEx(key, 'SteamPath')[0])
        except ImportError, OSError:
            pass
    libraries = []
    for root in roots:
        libraries.append(root)
        try:  # the other libraries are listed as "path" "..." lines
            with open(os.path.join(root, 'steamapps', 'libraryfolders.vdf'), encoding='utf-8', errors='replace') as f:
                for line in f:
                    parts = line.split('"')
                    if len(parts) >= 4 and parts[1] == 'path':
                        libraries.append(parts[3].replace('\\\\', '\\'))
        except OSError:
            pass
    return libraries


def candidates() -> list[str]:
    """The places an installation is usually found, likeliest first."""
    out = [os.path.join(library, 'steamapps', 'common', GAME_DIRECTORY) for library in steam_libraries()]
    home = os.path.expanduser('~')
    for name in (GAME_DIRECTORY, 'EVERSPACE™'):  # GOG, as its installer, Heroic and Lutris place it
        out += [
            os.path.join(home, 'GOG Games', name),
            os.path.join(home, 'Games', name),
            os.path.join(home, 'Games', 'Heroic', name),
        ]
        if sys.platform == 'win32':
            drive = os.environ.get('SystemDrive', 'C:') + os.sep
            out += [
                os.path.join(drive, 'GOG Games', name),
                os.path.join(os.environ.get('ProgramFiles(x86)', drive), 'GOG Galaxy', 'Games', name),
            ]
    return list(dict.fromkeys(os.path.normpath(c) for c in out))


def find_game() -> str | None:
    """The game's installation directory if it is in one of the usual places, or None."""
    for c in candidates():
        if os.path.isdir(os.path.join(c, PAKS)):
            return c
    return None


def save_dirs() -> list[str]:
    """The places the game keeps its saves, likeliest first. The Linux build keeps them in the
    user's configuration directory. The Windows build keeps them in the user's local
    application data, and Proton puts that inside the game's prefix in a Steam library."""
    home = os.path.expanduser('~')
    out = []
    if sys.platform == 'win32':
        local = os.environ.get('LOCALAPPDATA') or os.path.join(home, 'AppData', 'Local')
        out.append(os.path.join(local, SAVES))
    else:
        config = os.environ.get('XDG_CONFIG_HOME') or os.path.join(home, '.config')
        out.append(os.path.join(config, 'Epic', SAVES))
    prefix = os.path.join('pfx', 'drive_c', 'users', 'steamuser', 'AppData', 'Local')
    out += [os.path.join(library, 'steamapps', 'compatdata', STEAM_APP, prefix, SAVES) for library in steam_libraries()]
    return list(dict.fromkeys(os.path.normpath(c) for c in out))


def find_save_dir() -> str | None:
    """The game's SaveGames directory, if it is in one of the places the game puts it."""
    return next((c for c in save_dirs() if os.path.isdir(c)), None)


def cache_dir() -> str:
    """Where what is read from the installed game is kept, so that it is read once."""
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
    elif sys.platform == 'darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Caches')
    else:
        base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
    return os.path.join(base, 'es1save')
