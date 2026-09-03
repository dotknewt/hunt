from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import HuntError

CONF_NAME = "hunt.conf"

_KEYS = ("VAULT_PATH", "VAULT_BRANCH")
_LINE_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"$')

MAIN_BRANCH = "main"
# git check-ref-format, reduced to what a branch name may be.
_BRANCH_RE = re.compile(r"(?!/)(?!.*[/.]{2})(?!.*[/.]$)[A-Za-z0-9._/-]+")


class ConfigError(HuntError):
    pass


@dataclass(frozen=True)
class Config:
    vault_path: Path
    vault_branch: str


def find_config(start: Path | None = None) -> Path:
    override = os.environ.get("HUNT_CONF")
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise ConfigError(f"HUNT_CONF is set to {path}, which is not a file")
        return path
    here = (start if start is not None else Path.cwd()).expanduser()
    here = here.resolve()
    if here.is_file():
        here = here.parent
    for directory in (here, *here.parents):
        candidate = directory / CONF_NAME
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"no {CONF_NAME} found in {here} or any parent directory; "
        f"create one there or set HUNT_CONF"
    )


def load_config(path: Path | None = None) -> Config:
    conf = path if path is not None else find_config()
    try:
        text = conf.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {conf}: {exc}") from exc

    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if match is None:
            raise ConfigError(f'{conf}:{number}: expected KEY="value", got: {raw}')
        key, value = match.group(1), match.group(2)
        if key not in _KEYS:
            raise ConfigError(
                f"{conf}:{number}: unknown key {key}; only {' and '.join(_KEYS)} are allowed"
            )
        if key in values:
            raise ConfigError(f"{conf}:{number}: duplicate key {key}")
        values[key] = value

    missing = [key for key in _KEYS if key not in values]
    if missing:
        raise ConfigError(f"{conf}: missing required key(s): {', '.join(missing)}")

    raw_path = values["VAULT_PATH"]
    if raw_path.startswith("~") and not raw_path.startswith("~/"):
        raise ConfigError(
            f"{conf}: VAULT_PATH must not use ~user expansion, got: {raw_path!r}"
        )
    vault_path = Path(raw_path).expanduser()
    if not vault_path.is_absolute():
        raise ConfigError(
            f"{conf}: VAULT_PATH must be an absolute path after ~ expansion, got: "
            f"{raw_path!r}"
        )
    if any(part in (".", "..") for part in vault_path.parts):
        raise ConfigError(
            f"{conf}: VAULT_PATH must not contain '.' or '..' components, got: {raw_path!r}"
        )
    return Config(vault_path=vault_path, vault_branch=_branch(conf, values["VAULT_BRANCH"]))


def _branch(conf: Path, branch: str) -> str:
    """vault-spec 1.2: refuse an unusable branch here, so no later check can be
    skipped and let it through."""
    if not branch:
        raise ConfigError(f"{conf}: VAULT_BRANCH must not be empty")
    if branch == MAIN_BRANCH:
        raise ConfigError(
            f"{conf}: VAULT_BRANCH must not be '{MAIN_BRANCH}': it is the record, "
            "and hunt never writes on it"
        )
    if branch.startswith("-"):
        raise ConfigError(
            f"{conf}: VAULT_BRANCH must not begin with '-': git would read "
            f"{branch!r} as an option"
        )
    if any(character < "!" or character > "~" for character in branch):
        raise ConfigError(
            f"{conf}: VAULT_BRANCH must be printable ASCII without spaces, got: {branch!r}"
        )
    if not _BRANCH_RE.fullmatch(branch):
        raise ConfigError(f"{conf}: VAULT_BRANCH is not a valid git branch name: {branch!r}")
    return branch
