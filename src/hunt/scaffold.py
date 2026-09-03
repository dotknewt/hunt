"""The files `hunt init` puts in a vault, so that Obsidian, git and CI behave.

vault-spec 5 lists this set normatively; the contents of the two dotfiles are
normative there too, and the workflow and the three `.obsidian` files are not. Everything here is
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

WORKFLOW = """\
# Written by `hunt init` (vault-spec 5). The vault's continuous integration:
# vault-spec 8 requires the validation duties below to run on every merge
# candidate and in a branch protection rule on `main`, because the tool itself
# never pushes. Edit freely; hunt never overwrites this file once it exists.
#
# Branch protection to set on `main` (GitHub: Settings > Branches, or a
# ruleset): require a pull request, require the `validate` and
# `line-endings` checks to pass, and forbid force pushes and deletion.
name: hunt

on:
  push:
    branches: [main]
  pull_request:

env:
  # The hunt revision this vault validates against. Pin to a tag or commit of
  # https://github.com/dotknewt/hunt once one is chosen; `main` tracks the tool.
  HUNT_REF: main

jobs:
  validate:
    # card-spec 8.1: snapshot validation of the tree under review, including
    # duplicate ids and filenames, numbering gaps, and CR bytes in any
    # committed blob (vault-spec 8).
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          # Full history: transition validation below compares against main.
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v5
      - name: point hunt at this checkout
        run: |
          printf 'VAULT_PATH="%s"\\nVAULT_BRANCH="ci"\\n' "$GITHUB_WORKSPACE" \\
            > "$RUNNER_TEMP/hunt.conf"
          echo "HUNT_CONF=$RUNNER_TEMP/hunt.conf" >> "$GITHUB_ENV"
      - name: hunt validate
        run: uvx --from "git+https://github.com/dotknewt/hunt@$HUNT_REF" hunt validate
      - name: transition validation against main (card-spec 8.2)
        # Not enforced yet: `hunt validate --against <rev>` does not exist.
        # When it does, replace the echo with:
        #   uvx --from "git+https://github.com/dotknewt/hunt@$HUNT_REF" \\
        #     hunt validate --against origin/main
        if: github.event_name == 'pull_request'
        run: echo "transition validation (card-spec 8.2) is not implemented yet"

  line-endings:
    # vault-spec 8, independent of hunt itself: no committed blob on the branch
    # under review may hold a CR byte, whatever .gitattributes says.
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: no CR byte in any committed text file
        run: |
          fail=0
          while IFS= read -r f; do
            if git show "HEAD:$f" | grep -qU $'\\r'; then
              echo "CR byte in $f" >&2
              fail=1
            fi
          done < <(git grep -zIl '' HEAD | tr '\\0' '\\n' | sed 's/^HEAD://')
          exit $fail
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
        ".github/workflows/hunt.yml": WORKFLOW,
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
