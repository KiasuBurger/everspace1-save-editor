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

"""The game's icons as the editor uses them: where it keeps them as PNG files, and the
textures it draws with.

gameicons.py reads the textures out of the game. The game data names the icon of each item
and resource. extract() writes those icons to the cache when the editor reads the game, and
IconStore finds them there afterwards. A PNG has the path of its texture below /Game/, for
example UI/HUD/Images/Equipment/equip_dev_energy_shield.png.
"""

import os
import shutil
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from .. import gameicons, gamepaths

if TYPE_CHECKING:
    from ..gamedata import GameData
    from .gtk import Gdk

MARKER = 'UI'  # the folder that every icon is below


def cache_dir() -> str:
    """Where the editor keeps the extracted icons."""
    return os.path.join(gamepaths.cache_dir(), 'icons')


def extract(
    game: str, names: Iterable[str], destination: str, progress: Callable[[int, int], object] | None = None
) -> int:
    """Writes the icons `names` (texture paths from the game data) of the game at `game` to
    destination as PNG files. Returns the number of files that it wrote. It replaces what is
    in destination. If it fails, it leaves destination as it was. Raises OSError, or
    ValueError if the game's files are not as expected."""
    partial = destination + '.partial'
    shutil.rmtree(partial, ignore_errors=True)
    written = 0
    try:
        for name, data in gameicons.read_icons(game, names, progress):
            path = os.path.join(partial, *name.split('/')) + '.png'
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb') as f:
                f.write(data)
            written += 1
        if not written:
            raise ValueError('none of the icons in %s could be read' % os.path.join(game, gamepaths.PAKS))
        shutil.rmtree(destination, ignore_errors=True)
        os.replace(partial, destination)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return written


def find_icons(explicit: str | None = None) -> str | None:
    """The folder of extracted icons: the given one, or else the one in the user's cache. None
    if the icons are not there."""
    directory = explicit or cache_dir()
    return os.path.abspath(directory) if os.path.isdir(os.path.join(directory, MARKER)) else None


class IconStore:
    """Textures from the extracted icons. Every lookup can return None."""

    def __init__(self, directory: str | None) -> None:
        self.directory = directory
        self._loaded: dict[str, Gdk.Texture | None] = {}

    def texture(self, name: str | None) -> Gdk.Texture | None:
        """The texture of an icon by its name in the game data."""
        if not self.directory or not name:
            return None
        if name not in self._loaded:
            from .gtk import Gdk, GLib

            path = os.path.join(self.directory, *name.split('/')) + '.png'
            try:
                self._loaded[name] = Gdk.Texture.new_from_filename(path) if os.path.isfile(path) else None
            except GLib.Error:
                self._loaded[name] = None
        return self._loaded[name]

    def has_all(self, names: Iterable[str]) -> bool:
        """Whether the folder has a PNG file for each of the icons `names`."""
        directory = self.directory
        if not directory:
            return False
        return all(os.path.isfile(os.path.join(directory, *name.split('/')) + '.png') for name in names)

    def item(self, game: GameData, path: str) -> Gdk.Texture | None:
        """The icon of an item or resource by its class path."""
        return self.texture(game.icon(path))
