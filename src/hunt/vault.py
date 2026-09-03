from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .config import Config

from . import HuntError

MAIN_BRANCH = "main"


class VaultError(HuntError):
    pass


def _git(vault: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(vault), *args],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise VaultError("git is not installed or not on PATH") from None
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit status {proc.returncode}"
        raise VaultError("git " + " ".join(args) + ": " + detail)
    return proc


def _head_branch(vault: Path) -> str | None:
    proc = _git(vault, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _has_branch(vault: Path, branch: str) -> bool:
    proc = _git(vault, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch, check=False)
    return proc.returncode == 0


def _has_commits(vault: Path) -> bool:
    proc = _git(vault, "rev-parse", "--verify", "--quiet", "HEAD", check=False)
    return proc.returncode == 0


def is_repo(vault: Path) -> bool:
    vault = Path(vault)
    if not vault.is_dir():
        return False
    proc = _git(vault, "rev-parse", "--show-toplevel", check=False)
    if proc.returncode != 0:
        return False
    top = proc.stdout.strip()
    if not top:
        return False
    return Path(top).resolve() == vault.resolve()


def _enclosing_repo(vault: Path) -> Path | None:
    """The repository that already contains this path, if any (vault-spec 5)."""
    proc = _git(Path(vault), "rev-parse", "--show-toplevel", check=False)
    if proc.returncode != 0:
        return None
    top = proc.stdout.strip()
    if not top:
        return None
    top_path = Path(top).resolve()
    return None if top_path == Path(vault).resolve() else top_path


def init(vault: Path, branch: str) -> None:
    vault = Path(vault)
    if vault.exists() and not vault.is_dir():
        raise VaultError(f"vault path is not a directory: {vault}")
    vault.mkdir(parents=True, exist_ok=True)

    if not is_repo(vault):
        enclosing = _enclosing_repo(vault)
        if enclosing is not None:
            raise VaultError(
                f"refusing to initialize {vault} inside the repository at {enclosing}: "
                "the vault must be its own repository"
            )
        _git(vault, "init", "--initial-branch=" + MAIN_BRANCH)

    if not _has_branch(vault, MAIN_BRANCH):
        if _has_commits(vault):
            raise VaultError(
                f"{vault} is a git repository with history but no '{MAIN_BRANCH}' branch; "
                f"create '{MAIN_BRANCH}' before running 'hunt init'"
            )
        if _head_branch(vault) != MAIN_BRANCH:
            _git(vault, "checkout", "-b", MAIN_BRANCH)
        _git(vault, "commit", "--allow-empty", "-m", "hunt: init")

    if not _has_branch(vault, branch):
        _git(vault, "branch", branch, MAIN_BRANCH)
    if _head_branch(vault) != branch:
        _git(vault, "checkout", branch)


def current_branch(vault: Path) -> str:
    branch = _head_branch(Path(vault))
    if branch is None:
        raise VaultError(f"vault {vault} has no branch checked out (detached HEAD)")
    return branch


def is_clean(vault: Path) -> bool:
    proc = _git(Path(vault), "status", "--porcelain")
    return proc.stdout.strip() == ""


def contains_main(vault: Path, branch: str) -> bool:
    proc = _git(Path(vault), "merge-base", "--is-ancestor", MAIN_BRANCH, branch, check=False)
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    detail = proc.stderr.strip() or f"exit status {proc.returncode}"
    raise VaultError(f"git merge-base --is-ancestor {MAIN_BRANCH} {branch}: {detail}")


def ensure_writable(config: "Config") -> None:
    vault = Path(config.vault_path)
    branch = config.vault_branch

    if not vault.is_dir():
        raise VaultError(f"vault path does not exist: {vault}")
    if not is_repo(vault):
        raise VaultError(f"vault is not a git repository: {vault}; run 'hunt init'")
    if not _has_branch(vault, branch):
        raise VaultError(f"branch '{branch}' does not exist in {vault}; run 'hunt init'")

    head = current_branch(vault)
    if head != branch:
        raise VaultError(
            f"vault is on branch '{head}', not '{branch}'; "
            f"run 'git -C {vault} checkout {branch}' first"
        )
    if branch == MAIN_BRANCH:
        raise VaultError(
            f"refusing to write on '{MAIN_BRANCH}': it is the record; "
            "set VAULT_BRANCH to a working branch"
        )
    if not is_clean(vault):
        raise VaultError(
            f"vault work tree is not clean: commit or stash the changes in {vault} first"
        )
    if not contains_main(vault, branch):
        raise VaultError(
            f"branch '{branch}' does not contain '{MAIN_BRANCH}'; "
            f"merge or rebase '{MAIN_BRANCH}' into '{branch}' first"
        )


def safe_path(vault: Path, *parts: str) -> Path:
    root = Path(vault)
    segments: list[str] = []
    for part in parts:
        piece = Path(part)
        if piece.is_absolute():
            raise VaultError(f"path component must be relative to the vault: {part}")
        for segment in piece.parts:
            if segment == "..":
                raise VaultError(f"path component must not escape the vault: {part}")
            segments.append(segment)
    if not segments:
        raise VaultError("no path given")

    current = root
    for segment in segments:
        current = current / segment
        if current.is_symlink():
            raise VaultError(f"refusing to follow a symlink inside the vault: {current}")
    return current


def _relative(vault: Path, path: Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        # A relative path is still allowed to escape via "..", so resolve it
        # against the vault and confirm it stays inside.
        resolved = (Path(vault) / candidate).resolve()
        try:
            resolved.relative_to(Path(vault).resolve())
        except ValueError:
            raise VaultError(f"path is outside the vault: {candidate}") from None
        return candidate.as_posix()
    try:
        return candidate.relative_to(vault).as_posix()
    except ValueError:
        pass
    try:
        return candidate.resolve().relative_to(Path(vault).resolve()).as_posix()
    except ValueError:
        raise VaultError(f"path is outside the vault: {candidate}") from None


def commit(vault: Path, paths: Iterable[Path], message: str) -> None:
    vault = Path(vault)
    relative = [_relative(vault, path) for path in paths]
    if not relative:
        raise VaultError("commit requires at least one path")
    _git(vault, "add", "--", *relative)
    _git(vault, "commit", "-m", message, "--", *relative)
