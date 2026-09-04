from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .config import Config

from . import HuntError

MAIN_BRANCH = "main"

# vault-spec 3: environment artifacts. Exempt from the root inventory wherever
# they appear, and deletable precisely because no author wrote them.
OS_ARTIFACTS = frozenset({".DS_Store", "Thumbs.db"})
# vault-spec 3: the non-card files the vault root may hold.
ROOT_FILES = frozenset({".gitignore", ".gitattributes"})
# vault-spec 6: the only subject hunt writes that is not a card commit.
INIT_SUBJECT = "hunt: init"


class VaultError(HuntError):
    pass


def _git(vault: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git inside `vault`, capturing text output. With check=True a
    non-zero exit becomes a VaultError carrying git's own message."""
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
    """Name of the checked-out branch, or None on a detached HEAD."""
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
    """True only when `vault` is itself the top level of a repository, not
    merely inside one."""
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


def init(vault: Path, branch: str, prepare=None) -> list[Path]:
    """Create the repository, `main`, and the working branch (vault-spec 5).

    `prepare(vault) -> list[Path]` runs only when this call creates the root
    commit, and whatever it writes goes into that commit. That is what puts the
    vault scaffold - .gitattributes above all, on which the LF guarantee of
    vault-spec 8 rests - in place before any card is committed on any branch,
    and inherits it into every branch forked from `main`. Returns the paths it
    committed, empty when `main` already existed.
    """
    vault = Path(vault)
    # vault-spec 3: a directory, not a symlink to one. is_dir() follows the
    # link, so it has to be asked separately.
    if vault.is_symlink():
        raise VaultError(f"vault path is a symlink, not a directory: {vault}")
    if vault.exists() and not vault.is_dir():
        raise VaultError(f"vault path is not a directory: {vault}")

    # vault-spec 5 requires every check before any write, so that the vault is
    # untouched when a command refuses. The mkdir therefore waits until the
    # enclosing-repository refusal has had its say.
    if not is_repo(vault):
        enclosing = _enclosing_repo(vault)
        if enclosing is not None:
            raise VaultError(
                f"refusing to initialize {vault} inside the repository at {enclosing}: "
                "the vault must be its own repository"
            )
        vault.mkdir(parents=True, exist_ok=True)
        _git(vault, "init", "--initial-branch=" + MAIN_BRANCH)

    written: list[Path] = []
    if not _has_branch(vault, MAIN_BRANCH):
        if _has_commits(vault):
            raise VaultError(
                f"{vault} is a git repository with history but no '{MAIN_BRANCH}' branch; "
                f"create '{MAIN_BRANCH}' before running 'hunt init'"
            )
        if _head_branch(vault) != MAIN_BRANCH:
            _git(vault, "checkout", "-b", MAIN_BRANCH)
        if prepare is not None:
            written = list(prepare(vault))
        if written:
            names = [_relative(vault, path) for path in written]
            _git(vault, "add", "--", *names)
            _refuse_staged_cr(vault, names)
        proc = _git(vault, "commit", "--allow-empty", "-m", INIT_SUBJECT, check=False)
        if proc.returncode != 0:
            raise VaultError(
                f"could not create the first commit in {vault}: "
                + (proc.stderr.strip() or proc.stdout.strip())
                + "; git needs user.name and user.email to be set"
            )

    if not _has_branch(vault, branch):
        _git(vault, "branch", branch, MAIN_BRANCH)
    if _head_branch(vault) != branch:
        # `hunt init` does not require a clean tree, so this checkout can fail
        # on conflicting local changes - or worse, succeed and carry them onto
        # the working branch.
        proc = _git(vault, "checkout", branch, check=False)
        if proc.returncode != 0:
            raise VaultError(
                f"could not check out '{branch}' in {vault}: "
                + (proc.stderr.strip() or proc.stdout.strip())
                + "; commit or stash your changes first"
            )
    return written


def current_branch(vault: Path) -> str:
    branch = _head_branch(Path(vault))
    if branch is None:
        raise VaultError(f"vault {vault} has no branch checked out (detached HEAD)")
    return branch


def is_clean(vault: Path) -> bool:
    proc = _git(Path(vault), "status", "--porcelain")
    return proc.stdout.strip() == ""


def contains_main(vault: Path, branch: str) -> bool:
    """Whether `branch` has `main` in its history (exit 1 from merge-base
    means "no", anything else is an error)."""
    proc = _git(Path(vault), "merge-base", "--is-ancestor", MAIN_BRANCH, branch, check=False)
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    detail = proc.stderr.strip() or f"exit status {proc.returncode}"
    raise VaultError(f"git merge-base --is-ancestor {MAIN_BRANCH} {branch}: {detail}")


def ensure_writable(config: "Config") -> None:
    """Preflight for every writing command (vault-spec 4/5): repo exists, the
    configured branch exists, is checked out, is not main, the tree is clean
    and the branch contains main. Raises VaultError on the first failure."""
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
    """Join `parts` onto the vault root, refusing absolute parts, "..", and any
    symlink met along the way, so a write can never land outside the vault."""
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
    """Vault-relative posix form of `path` for git's command line; raises if
    the path is outside the vault."""
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


def ensure_on_branch(vault: Path, branch: str) -> None:
    """vault-spec 4: HEAD must be VAULT_BRANCH, and VAULT_BRANCH is never main.

    ensure_writable asks the same two questions, but as a preflight some time
    before the commit. This is the version the commit path itself asks, so that
    no caller - and no branch switch between preflight and commit - can make the
    tool the thing that writes on `main` or on a branch it was not given.
    """
    vault = Path(vault)
    if branch == MAIN_BRANCH:
        raise VaultError(
            f"refusing to commit on '{MAIN_BRANCH}': it is the record; "
            "set VAULT_BRANCH to a working branch"
        )
    head = _head_branch(vault)
    if head is None:
        raise VaultError(
            f"refusing to commit: vault {vault} has no branch checked out (detached HEAD), "
            f"expected '{branch}'"
        )
    if head != branch:
        raise VaultError(
            f"refusing to commit: vault is on branch '{head}', not '{branch}'; "
            f"run 'git -C {vault} checkout {branch}' first"
        )


def commit(vault: Path, paths: Iterable[Path], message: str, branch: str) -> None:
    """Stage exactly `paths` and commit them on `branch`, which HEAD must be."""
    vault = Path(vault)
    relative = [_relative(vault, path) for path in paths]
    if not relative:
        raise VaultError("commit requires at least one path")
    ensure_on_branch(vault, branch)
    _git(vault, "add", "--", *relative)
    _refuse_staged_cr(vault, relative)
    # Asked again after staging: `git add` is the first thing this function
    # does to the repository, and the commit is the one act that must never
    # land on the wrong branch, so the check sits as close to it as it can.
    try:
        ensure_on_branch(vault, branch)
    except VaultError:
        _git(vault, "reset", "--quiet", "--", *relative, check=False)
        raise
    _git(vault, "commit", "-m", message, "--", *relative)


def _staged_blob(vault: Path, relative: str) -> bytes:
    """The bytes git would record for a path, after any autocrlf conversion."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(vault), "show", ":" + relative], capture_output=True
        )
    except FileNotFoundError:
        raise VaultError("git is not installed or not on PATH") from None
    return proc.stdout if proc.returncode == 0 else b""


def _refuse_staged_cr(vault: Path, relative: Iterable[str]) -> None:
    """vault-spec 8: hunt is never the thing that records a carriage return.

    The check reads the staged blob rather than the working tree, because it is
    the staged bytes that a commit records and a Windows core.autocrlf=true can
    put a CR there that the file on disk does not have.
    """
    for name in relative:
        if b"\r" not in _staged_blob(vault, name):
            continue
        _git(vault, "reset", "--quiet", "--", *relative, check=False)
        raise VaultError(
            f"refusing to commit {name}: its staged content contains a carriage "
            "return, and every committed byte must use LF line endings; check "
            f"core.autocrlf and {vault / '.gitattributes'}"
        )


def text_attributes(vault: Path, paths: Iterable[Path]) -> dict[str, dict[str, str]]:
    """What git's attributes say about the line endings of each path.

    Asking git beats parsing .gitattributes: precedence, negation and directory
    scope are its rules, and a validator that reimplemented them would disagree
    with the tool that actually converts the bytes.
    """
    vault = Path(vault)
    relative = [_relative(vault, path) for path in paths]
    if not relative:
        return {}
    proc = _git(vault, "check-attr", "-z", "text", "eol", "--", *relative)
    fields = proc.stdout.split("\0")
    attributes: dict[str, dict[str, str]] = {}
    for index in range(0, len(fields) - 2, 3):
        name, attribute, value = fields[index : index + 3]
        attributes.setdefault(name, {})[attribute] = value
    return attributes


def sweep(vault: Path) -> list[Path]:
    """Delete every environment artifact under the vault (vault-spec 3).

    A .DS_Store that Finder wrote while nobody was looking must not be able to
    block a write by dirtying the tree, and nothing authored it, so nothing is
    lost by removing it. Confined to those exact names, never inside .git, and
    never through a symlink.
    """
    root = Path(vault)
    removed: list[Path] = []
    if root.is_symlink() or not root.is_dir():
        return removed
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name != ".git":
                    stack.append(entry)
            elif entry.name in OS_ARTIFACTS:
                try:
                    entry.unlink()
                except OSError:
                    continue
                removed.append(entry)
    return removed


def resolve_revision(vault: Path, revision: str) -> str:
    """The commit a revision names, or a VaultError. `--against` is handed a
    branch, tag or sha by a human or a workflow; a typo has to say so rather
    than compare the tree against nothing and report all clear."""
    vault = Path(vault)
    if not isinstance(revision, str) or not revision or revision.startswith("-"):
        raise VaultError("not a revision: %r" % (revision,))
    proc = _git(
        vault, "rev-parse", "--verify", "--quiet", revision + "^{commit}", check=False
    )
    sha = proc.stdout.strip()
    if proc.returncode != 0 or not sha:
        raise VaultError("unknown revision: " + revision)
    return sha


def tracked_blobs(vault: Path, revision: str = "HEAD") -> list[tuple[str, bytes]]:
    """Every blob a revision records, as (path relative to the root, bytes).

    vault-spec 8: what a remote receives is the committed bytes, so that is what
    validation has to read. Once .gitattributes is in force git normalizes on
    check-in and the file on disk can no longer show the problem.
    """
    vault = Path(vault)
    tree = _git(vault, "ls-tree", "-r", "-z", revision, check=False)
    if tree.returncode != 0:
        return []

    entries = []
    for record in tree.stdout.split("\0"):
        if not record:
            continue
        metadata, name = record.split("\t", 1)
        _, kind, object_id = metadata.split(" ", 2)
        if kind == "blob":
            entries.append((name, object_id))
    if not entries:
        return []

    try:
        batch = subprocess.run(
            ["git", "-C", str(vault), "cat-file", "--batch"],
            input="".join(object_id + "\n" for _, object_id in entries).encode("ascii"),
            capture_output=True,
        )
    except FileNotFoundError:
        raise VaultError("git is not installed or not on PATH") from None
    if batch.returncode != 0:
        detail = batch.stderr.decode(errors="replace").strip() or f"exit status {batch.returncode}"
        raise VaultError(f"git cat-file --batch: {detail}")

    blobs = []
    offset = 0
    for name, object_id in entries:
        header_end = batch.stdout.find(b"\n", offset)
        if header_end < 0:
            raise VaultError("git cat-file --batch: incomplete response")
        header = batch.stdout[offset:header_end].decode("ascii", errors="replace")
        parts = header.split()
        if len(parts) != 3 or parts[0] != object_id or parts[1] != "blob":
            raise VaultError(f"git cat-file --batch: unexpected response {header!r}")
        size = int(parts[2])
        start = header_end + 1
        end = start + size
        if end >= len(batch.stdout) or batch.stdout[end : end + 1] != b"\n":
            raise VaultError("git cat-file --batch: incomplete blob")
        blobs.append((name, batch.stdout[start:end]))
        offset = end + 1
    return blobs


def ignored(vault: Path, paths: Iterable[Path]) -> set[str]:
    """Which of these paths a .gitignore hides, as vault-relative posix names."""
    vault = Path(vault)
    relative = [_relative(vault, path) for path in paths]
    if not relative:
        return set()
    try:
        proc = subprocess.run(
            # --no-index: without it git skips tracked paths, and a card that
            # is tracked today is exactly the one that vanishes tomorrow when
            # someone removes and re-adds it.
            ["git", "-C", str(vault), "check-ignore", "--no-index", "--stdin", "-z"],
            input="\0".join(relative),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise VaultError("git is not installed or not on PATH") from None
    # 0: some path is ignored. 1: none is. Anything else is a real failure, and
    # a validator that cannot ask must not answer "nothing is hidden".
    if proc.returncode not in (0, 1):
        detail = proc.stderr.strip() or f"exit status {proc.returncode}"
        raise VaultError(f"git check-ignore in {vault}: {detail}")
    return {name for name in proc.stdout.split("\0") if name}
