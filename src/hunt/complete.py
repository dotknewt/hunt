"""Completion candidates.

Nothing here raises. A completion helper that prints a traceback into the
user's prompt is worse than one that offers nothing, so an unreadable config,
an absent vault, and a permission error all yield an empty list. Set
HUNT_COMPLETE_DEBUG=1 to see the exception on stderr instead, so a typo'd
hunt.conf stays diagnosable.
"""

from __future__ import annotations

import os
import sys
import traceback

from . import cards
from .config import load_config


def _quiet(default):
    """Run a candidate producer, swallowing everything it can go wrong with."""

    def decorate(function):
        def wrapper(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except BaseException:  # noqa: BLE001 - see the module docstring
                if os.environ.get("HUNT_COMPLETE_DEBUG") == "1":
                    traceback.print_exc(file=sys.stderr)
                return list(default)

        wrapper.__name__ = function.__name__
        wrapper.__doc__ = function.__doc__
        return wrapper

    return decorate


@_quiet([])
def categories():
    from .cli import category_spellings

    return category_spellings()


@_quiet([])
def parent_ids():
    config = load_config()
    if config.vault_path is None or not config.vault_path.is_dir():
        return []
    found = []
    # Iterate the known category directories rather than globbing */*: never
    # descend into .obsidian/, never follow a symlink out of the vault.
    for directory in sorted(cards.DIRECTORIES):
        category = config.vault_path / directory
        if category.is_symlink() or not category.is_dir():
            continue
        for entry in category.iterdir():
            if entry.is_symlink() or not entry.is_dir():
                continue
            if cards.PARENT_RE.fullmatch(entry.name):
                found.append(entry.name)
    return sorted(found)
