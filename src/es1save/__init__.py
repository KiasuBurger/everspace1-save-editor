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

"""Reader, writer and editor for Everspace 1 savegames.

    import es1save
    save = es1save.load('CurrentRunSave.sav')
    save['properties']['Credits']['value'] += 1000
    es1save.dump(save, 'CurrentRunSave.sav')

Modules:
    savegame   the save format: the GVAS property tree
    profile    the pilot's progress (CurrentPlayerSave.sav): perks, blueprints, ships
    run        the run in progress (CurrentRunSave.sav): credits, resources, equipment
    gamedata   what the editor reads from the installed game
    editor     the save editor
"""

from .savegame import EncodeError, ParseError, build_gvas, dump, dumps, load, loads, parse_gvas

try:
    from ._version import __version__
except ImportError:  # a checkout that has not been built or installed
    __version__ = 'unknown'

__all__ = [
    'EncodeError',
    'ParseError',
    '__version__',
    'build_gvas',
    'dump',
    'dumps',
    'load',
    'loads',
    'parse_gvas',
]
