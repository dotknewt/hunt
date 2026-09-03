from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import HuntError

CONF_NAME = "hunt.conf"

_KEYS = ("VAULT_PATH", "VAULT_BRANCH")
# vault-spec 1.1: KEY="value", the key in SCREAMING_SNAKE_CASE. Anything
# else is a syntax error and not a key we happen not to know.
_LINE_RE = re.compile(r'^([A-Z][A-Z0-9_]*)="([^"]*)"$')

MAIN_BRANCH = "main"
# git check-ref-format, reduced to what a branch name may be.
_BRANCH_RE = re.compile(r"(?!/)(?!.*[/.]{2})(?!.*[/.]$)[A-Za-z0-9._/-]+")


class ConfigError(HuntError):
    pass


class ConfigUnset(ConfigError):
    """vault-spec 1.2: a key is present but empty, which means unconfigured.

    Kept distinct from a malformed file because the remedy differs: this one is
    the expected initial state of a fresh checkout, and the fix is to fill the
    file in or to pass the values to `hunt init`.
    """

    def __init__(self, path, keys):
        self.path = Path(path)
        self.keys = tuple(keys)
        super().__init__(
            "%s %s not set in %s"
            % (
                " and ".join(self.keys),
                "is" if len(self.keys) == 1 else "are",
                self.path,
            )
        )


@dataclass(frozen=True)
class Config:
    vault_path: Path | None
    vault_branch: str | None
    path: Path | None = None
    """The hunt.conf these values came from, so a refusal can name it."""

    @property
    def unset(self) -> tuple[str, ...]:
        """The keys that are present in the file but empty (vault-spec 1.2)."""
        pairs = (("VAULT_PATH", self.vault_path), ("VAULT_BRANCH", self.vault_branch))
        return tuple(key for key, value in pairs if value is None)


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

    return Config(
        vault_path=_vault_path(conf, values["VAULT_PATH"]),
        vault_branch=_branch(conf, values["VAULT_BRANCH"]),
        path=conf,
    )


def require_configured(config: Config) -> Config:
    """Refuse before any write when a value the command needs is unconfigured."""
    if config.unset:
        raise ConfigUnset(config.path, config.unset)
    return config


def load_configured(path: Path | None = None) -> Config:
    return require_configured(load_config(path))


def _vault_path(conf: Path, raw_path: str) -> Path | None:
    if not raw_path:
        return None
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
    return vault_path


def _branch(conf: Path, branch: str) -> str | None:
    """vault-spec 1.2: refuse an unusable branch here, so no later check can be
    skipped and let it through. An empty value is unconfigured, not unusable."""
    if not branch:
        return None
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


def write_config(path: Path, values: dict[str, str]) -> Path:
    """Set keys in an existing hunt.conf, or create one holding just them.

    Assignment lines for the given keys are rewritten in place and absent keys
    are appended; every other line passes through verbatim. vault-spec 1.1
    permits comments, so a whole-file rewrite from a dict would silently delete
    the user's own notes. The write is atomic and the result is re-parsed before
    it replaces the original, so a bug here cannot leave an unreadable config.
    """
    conf = Path(path)
    for key, value in values.items():
        if key not in _KEYS:
            raise ConfigError(f"refusing to write unknown key {key}")
        if not _LINE_RE.match(f'{key}="{value}"'):
            raise ConfigError(f"refusing to write unquotable value for {key}: {value!r}")

    if conf.exists():
        try:
            original = conf.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"cannot read {conf}: {exc}") from exc
    else:
        original = ""

    lines = original.splitlines()
    remaining = dict(values)
    for index, raw in enumerate(lines):
        match = _LINE_RE.match(raw.strip())
        if match is None:
            continue
        key = match.group(1)
        if key in remaining:
            lines[index] = f'{key}="{remaining.pop(key)}"'
    for key in _KEYS:  # append in schema order, not dict order
        if key in remaining:
            lines.append(f'{key}="{remaining.pop(key)}"')

    text = "".join(line + "\n" for line in lines)
    if not text.isascii():
        raise ConfigError(f"{conf}: refusing to write non-ASCII configuration")

    temporary = conf.with_name(conf.name + ".hunt-tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(text.encode("ascii"))
            handle.flush()
            os.fsync(handle.fileno())
        load_config(temporary)  # a config we cannot read back is not a config
        os.replace(temporary, conf)
    finally:
        if temporary.exists():
            temporary.unlink()
    return conf
