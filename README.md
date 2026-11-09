# Everspace 1 Save Editor

This program lets you edit your Everspace 1 saves: the pilot's progress, the regular run and
the hardcore run. If a run went wrong, or you want every perk without the grind, this is the
easy way out, if you can live with yourself. :-)

## Features

For the pilot:

* Set DNA fragments and Viridian Energy
* Unlock and upgrade perks
* Unlock blueprints, ships, glyphs and sub-routines
* Choose each ship's enhancements and starting loadout (A, B or C)

For regular runs:

* Set credits, fuel, hull and resources
* Add, remove or replace weapons, devices and consumables, and set their ammo or amount
* Add or remove mods on an item
* Add or remove buffs (the tuning station upgrades)
* Change the bonus gear of a run that hasn't started yet

For hardcore runs, additionally:

* Add or remove handicaps
* Set the run's own perks

## Impossible configurations

The game enforces a large number of conditions on items, so there are limits on how crazy you
can get. The main thing you can do is stack tuning station buffs and set their durations as long
as you want. You can also give yourself a Seeker battery with hundreds of reloads, and spam away
to your heart's content.

## Backups

The editor will automatically create a backup each time you save your changes.
This behaviour can be controlled in the Settings.

## Game Resources

The editor relies on the game to provide icons and item descriptions, and will extract these
from the game files the first time it runs. It tries to autodetect your game installation
directory, but if you have a sufficiently unusual configuration, you might have to specify it
manually. This does mean you cannot really run the editor on a system that doesn't have the game
installed, but why would you do that?

## Installation

### Windows

Download `es1save-<version>-windows.zip` from the latest release on the
[Releases](https://github.com/KiasuBurger/everspace1-save-editor/releases) page, unzip it
anywhere, and run `es1save-editor.exe` in the folder it contains. The folder has everything the
editor needs, so nothing else has to be installed.

The program is not signed, so Windows may warn about it the first time it is run; "More info"
and then "Run anyway" starts it.

### Linux

The editor needs Python 3.14 or later, GTK 4 and PyGObject. These normally come from the
distribution rather than from PyPI, for example:

```
sudo apt install python3-gi gir1.2-gtk-4.0          # Debian, Ubuntu
sudo dnf install python3-gobject gtk4               # Fedora
sudo pacman -S python-gobject gtk4                  # Arch
```

libadwaita (`gir1.2-adw-1`, `libadwaita`) is optional; with it the window follows the desktop's
light or dark setting and accent colour.

#### From a source checkout, with uv

```
git clone https://github.com/KiasuBurger/everspace1-save-editor.git
cd everspace1-save-editor
uv venv --system-site-packages --python /usr/bin/python3
uv sync
uv run es1save-editor
```

The environment is made on the system Python, with access to its packages, so that it sees
the distribution's PyGObject.

#### With pipx

```
pipx install --system-site-packages --python /usr/bin/python3 \
    git+https://github.com/KiasuBurger/everspace1-save-editor.git
es1save-editor
```

From a source checkout, `pipx install --system-site-packages --python /usr/bin/python3 .` does
the same.

Either way, `es1save-editor --install-desktop` adds the editor to the desktop's applications.
Run the editor once first, so that it has the game's icons to use for itself.

### macOS

The editor has not been tried on macOS; this is how it is expected to install. It needs
[Homebrew](https://brew.sh) for Python, GTK 4 and PyGObject:

```
brew install python@3.14 gtk4 pygobject3 libadwaita adwaita-icon-theme pipx
pipx install --system-site-packages --python "$(brew --prefix python@3.14)/bin/python3.14" \
    git+https://github.com/KiasuBurger/everspace1-save-editor.git
es1save-editor
```

`pygobject3` has to be built for the same Python that the editor runs on. If `brew info pygobject3`
names a later Python than 3.14, install that one instead and use it in the command above.

## Troubleshooting

If you find the program crashes on Windows, you can find the log file at
`%LOCALAPPDATA%\es1save\editor.log`. On Linux or MacOS, if you run
from a terminal, you will see the output directly.

When the editor stops normally, the last line of the log is
`es1save-editor stopped normally, exit status N`. If this line is not in the log, the
editor crashed. Some "Windows fatal exception" lines come from exceptions that Windows
handles, and after them the editor continues.

Please attach it when reporting problems.

## Licence

Copyright © 2026 KiasuBurger. This program is free software: you can redistribute it and
modify it under the terms of the GNU General Public License, version 3 or, at your option, any
later version. It comes with no warranty. The licence is in [LICENSE](LICENSE).
