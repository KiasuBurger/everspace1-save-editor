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

"""The saves being edited: loading, saving and backups.

The game keeps one pilot (CurrentPlayerSave.sav), one regular run (CurrentRunSave.sav) and one
hardcore run (CurrentHCRunSave.sav) in its SaveGames folder. A Session holds them together,
because the limits of a regular run come from the pilot's perks. The game also writes a
*_Backup.sav copy of each. The editor does not change those copies.

Nothing here touches GTK, so it can be tested without a display.
"""

import os
import re
import shutil
import sys
import time
from typing import Any

from .. import profile, run, savegame
from ..savegame import Properties, Save

PLAYER_FILE = 'CurrentPlayerSave.sav'
RUN_FILE = 'CurrentRunSave.sav'
HARDCORE_FILE = 'CurrentHCRunSave.sav'
KINDS = {profile.CLASS: 'player', run.CLASS: 'run'}


class Document:
    """One save file and its tree."""

    def __init__(self, path: str, save: Save) -> None:
        self.path = path
        self.save = save
        self.dirty = False
        self.kind = KINDS.get(save['header'].get('save_game_class', ''), '')

    @classmethod
    def load(cls, path: str) -> Document:
        save = savegame.load(path)
        found = save['header'].get('save_game_class', '')
        if found not in KINDS:
            raise ValueError(
                '%s is not an Everspace save (it holds %s)' % (os.path.basename(path), found or 'no save class')
            )
        return cls(path, save)

    @property
    def slot(self) -> str:
        """The place of the save in a Session: player, run or hardcore."""
        if self.kind == 'run' and run.hardcore(self.properties):
            return 'hardcore'
        return self.kind

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def properties(self) -> Properties:
        props: Properties = self.save['properties']
        return props

    def write(
        self, path: str | None = None, backup_dir: str | None = None, keep: int | None = None, backup: bool = True
    ) -> str | None:
        """Writes the save to `path` (default: where it came from). Unless `backup` is False, an
        existing file is first copied to `backup_dir`. That directory then keeps no more than
        the newest `keep` copies of the file (all of them if None). Returns the copy's path."""
        path = path or self.path
        data = savegame.dumps(self.save)
        kept = backup_file(path, backup_dir, keep) if backup and os.path.exists(path) else None
        tmp = path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
        self.path = path
        self.dirty = False
        return kept


class Session:
    """The pilot, the regular run and the hardcore run. Any of them can be missing."""

    def __init__(
        self, player: Document | None = None, run_doc: Document | None = None, hardcore: Document | None = None
    ) -> None:
        self.player = player
        self.run = run_doc
        self.hardcore = hardcore

    @classmethod
    def open(cls, path: str) -> Session:
        """Opens a save, and the other saves from the same folder that are there. `path` can
        also be the folder."""
        if os.path.isdir(path):
            folder, first = path, None
        else:
            folder, first = os.path.dirname(os.path.abspath(path)), Document.load(path)
        session = cls()
        if first:
            setattr(session, first.slot, first)
        for slot, name in (('player', PLAYER_FILE), ('run', RUN_FILE), ('hardcore', HARDCORE_FILE)):
            other = os.path.join(folder, name)
            if getattr(session, slot) is None and os.path.isfile(other):
                doc = Document.load(other)
                if doc.slot == slot:
                    setattr(session, slot, doc)
        if not session.documents:
            raise ValueError('no Everspace saves in %s' % folder)
        return session

    @property
    def documents(self) -> list[Document]:
        return [d for d in (self.player, self.run, self.hardcore) if d]

    @property
    def dirty(self) -> bool:
        return any(d.dirty for d in self.documents)

    @property
    def folder(self) -> str:
        return os.path.dirname(os.path.abspath(self.documents[0].path))

    def player_props(self) -> Properties | None:
        return self.player.properties if self.player else None

    def write(self, backup_dir: str | None = None, keep: int | None = None, backup: bool = True) -> list[str]:
        """Writes the saves that have changes. Returns the paths of the backup copies."""
        kept = []
        for doc in self.documents:
            if doc.dirty:
                copy = doc.write(None, backup_dir, keep, backup)
                if copy:
                    kept.append(copy)
        return kept


def summary(doc: Document) -> dict[str, Any]:
    """A few values that say which pilot or run a save is."""
    props = doc.properties
    keys: tuple[str, ...]
    if doc.kind == 'player':
        keys = ('PlayerName', 'NumRuns', 'NumWins', 'Version')
    else:
        keys = ('ShipIndex', 'Credits', 'CurrentSystem')
    return {k: props[k]['value'] for k in keys if k in props}


def default_backup_dir() -> str:
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
    else:
        base = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(base, 'es1save', 'backups')


def backup_file(path: str, backup_dir: str | None = None, keep: int | None = None) -> str:
    """Copies a file into the backup directory, with the time in its name. Returns the copy.
    With `keep`, removes the older copies of the file, and keeps only the newest `keep`."""
    backup_dir = backup_dir or default_backup_dir()
    os.makedirs(backup_dir, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(path))
    stamp = time.strftime('%Y%m%d-%H%M%S')
    target = os.path.join(backup_dir, '%s.%s%s' % (stem, stamp, ext))
    n = 1
    while os.path.exists(target):
        n += 1
        target = os.path.join(backup_dir, '%s.%s-%d%s' % (stem, stamp, n, ext))
    shutil.copy2(path, target)
    if keep is not None:
        for old in backups_of(path, backup_dir)[keep:]:
            try:
                os.remove(old)
            except OSError:
                pass  # the copy stays. It does no harm.
    return target


def backups_of(path: str, backup_dir: str | None = None) -> list[str]:
    """The copies that backup_file made of the file at `path`, newest first."""
    backup_dir = backup_dir or default_backup_dir()
    stem, ext = os.path.splitext(os.path.basename(path))
    pattern = re.compile(re.escape(stem) + r'\.(\d{8}-\d{6})(?:-(\d+))?' + re.escape(ext) + '$')
    try:
        names = os.listdir(backup_dir)
    except OSError:
        return []
    found = []
    for name in names:
        m = pattern.match(name)
        if m:
            found.append(((m.group(1), int(m.group(2) or 1)), os.path.join(backup_dir, name)))
    return [p for _, p in sorted(found, reverse=True)]
