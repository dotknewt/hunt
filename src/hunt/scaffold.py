"""The files `hunt init` puts in a vault, so that Obsidian and git behave.

vault-spec 5 lists this set normatively; the contents of the two dotfiles are
normative there too, and the three `.obsidian` files are not. Everything here is
written only if absent, which is what keeps `hunt init` idempotent.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import cards
from .vault import VaultError, _git, safe_path

GITATTRIBUTES = """\
# vault-spec 8: every committed byte uses LF, whatever the checkout platform
# does. Git for Windows defaults to core.autocrlf=true, which would rewrite
# card files to CRLF and break both the byte rule of card-spec 3.1 and the
# re-render comparison hunt validate performs.
#
# text=auto, not a bare text: bare text normalizes binary files too and would
# corrupt any image or plugin asset that ends up under .obsidian/.
* text=auto eol=lf
"""

GITIGNORE = """\
# Obsidian's per-machine state. The rest of .obsidian/ is committed, so a vault
# opens configured on every machine.
.obsidian/workspace*.json
.obsidian/cache
.obsidian/plugins/
.obsidian/themes/

# Environment artifacts (vault-spec 3). hunt deletes these when it finds them;
# ignoring them keeps a stale one from dirtying the tree in the meantime.
.DS_Store
Thumbs.db
"""

APP = {
    # The defence that matters: edited as source, Obsidian's property UI cannot
    # rewrite a card's single-line `tags` flow sequence into a block sequence,
    # which card-spec 4 forbids and which would break every parent card.
    "propertiesInDocument": "source",
    # Without this Obsidian deletes into .trash/, which validation would report
    # as an unknown category directory for as long as the vault lives.
    "trashOption": "system",
    "alwaysUpdateLinks": True,
    "showUnsupportedFiles": False,
}

CORE_PLUGINS = {
    "file-explorer": True,
    "global-search": True,
    "switcher": True,
    "graph": True,
    "backlink": True,
    "outgoing-link": True,
    "tag-pane": True,
    "page-preview": True,
    "outline": True,
    "properties": True,
    "bases": False,
    "canvas": False,
    "daily-notes": False,
    "publish": False,
    "sync": False,
    "templates": False,
    "webviewer": False,
}

# Belt and braces behind propertiesInDocument: text for every key, so that no
# property is date-typed and rewritten unquoted (card-spec requires the quotes,
# and validate.py reports frontmatter.unquoted-date otherwise).
TYPES = {
    "types": {
        key: "text"
        for key in dict.fromkeys(cards.PARENT_KEYS + cards.RUN_KEYS)
    }
}


def _json(value):
    return json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n"


def files() -> dict[str, str]:
    """The scaffold, as vault-relative posix paths mapped to their contents."""
    return {
        ".gitattributes": GITATTRIBUTES,
        ".gitignore": GITIGNORE,
        ".obsidian/app.json": _json(APP),
        ".obsidian/core-plugins.json": _json(CORE_PLUGINS),
        ".obsidian/types.json": _json(TYPES),
    }


def missing(vault: Path) -> list[str]:
    """Which scaffold files a vault does not have yet."""
    return [name for name in files() if not safe_path(vault, name).exists()]


def scaffold(vault: Path, warn=None) -> list[Path]:
    """Write the absent scaffold files and return what was created.

    A path an existing .gitignore hides is skipped with a warning rather than
    written: vault.commit runs `git add -- <paths>`, which exits 1 on an
    explicitly named ignored path, so writing it would leave the vault
    permanently dirty. Forcing the add instead would override a decision the
    vault's owner made on purpose.
    """
    vault = Path(vault)
    contents = files()
    created: list[Path] = []
    for name in contents:
        target = safe_path(vault, name)
        if target.exists():
            continue
        if _ignored(vault, name):
            if warn is not None:
                warn(
                    f"not writing {name}: a .gitignore in {vault} hides it, so it "
                    "could never be committed"
                )
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        _write(target, contents[name])
        created.append(target)
    return created


def _ignored(vault: Path, name: str) -> bool:
    proc = _git(vault, "check-ignore", "--quiet", "--no-index", "--", name, check=False)
    if proc.returncode in (0, 1):
        return proc.returncode == 0
    detail = proc.stderr.strip() or f"exit status {proc.returncode}"
    raise VaultError(f"git check-ignore in {vault}: {detail}")


def _write(path: Path, text: str) -> None:
    if not text.isascii() or "\r" in text or not text.endswith("\n"):
        raise VaultError(f"refusing to write malformed scaffold content to {path}")
    with open(path, "wb") as handle:
        handle.write(text.encode("ascii"))
