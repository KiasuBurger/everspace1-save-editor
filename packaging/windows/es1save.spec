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

# PyInstaller's description of the Windows build: one folder, dist/es1save, holding
# es1save-editor.exe (the editor, without a console) with Python, GTK 4 and libadwaita
# beside it.
#
# It is built in MSYS2's UCRT64 environment, which is where GTK and PyGObject come from:
#
#   pyinstaller --noconfirm packaging/windows/es1save.spec

import os

root = os.path.abspath(os.path.join(SPECPATH, '..', '..'))
src = os.path.join(root, 'src')

editor = Analysis(
    [os.path.join(SPECPATH, 'editor.py')],
    pathex=[src],
    # the stylesheets are read from beside the editor's modules
    datas=[(os.path.join(src, 'es1save', 'editor', '*.css'), os.path.join('es1save', 'editor'))],
    # libadwaita draws the desktop's theme as Windows has it set, light or dark and in its
    # accent colour; the editor imports it only once it has looked for it
    hiddenimports=['gi.repository.Adw'],
    hooksconfig={
        'gi': {
            'module-versions': {'Gtk': '4.0', 'Gdk': '4.0', 'Adw': '1'},
            'icons': ['Adwaita'],
            'themes': ['Adwaita'],
            'languages': ['en'],
        },
    },
    # the modules go in the folder as .pyc files rather than into base_library.zip: mod sites
    # reject a download with a zip inside it
    noarchive=True,
)

exe = EXE(PYZ(editor.pure), editor.scripts, exclude_binaries=True, name='es1save-editor', console=False, upx=False)

COLLECT(exe, editor.binaries, editor.datas, name='es1save', upx=False)
