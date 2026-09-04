from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path


from . import cards, vault as vaultmod
from .vault import OS_ARTIFACTS, ROOT_FILES

# vault-spec 3: the directories whose contents the vault contract does not
# constrain. Everything else at the root is the card tree or a violation.
VAULT_DIRS = (".git", ".github", ".obsidian")

# Longest quoted value a finding message will show before truncating.
_QUOTE_LIMIT = 120

# cards.CardError codes -> finding codes. Anything not listed here surfaces as
# render.parse-error (see _card_error).
_CARD_ERROR_CODES = {
    "FILE-NON-ASCII": "bytes.non-ascii",
    "LAYOUT-MISSING-INDEX": "path.missing-index",
    "LAYOUT-BAD-RUN-FILENAME": "path.bad-run-filename",
    "FM-MISSING-FENCE": "frontmatter.missing-fence",
    "FM-PARSE-ERROR": "frontmatter.parse-error",
    "FM-DUPLICATE-KEY": "frontmatter.duplicate-key",
    "FM-MISSING-KEY": "frontmatter.missing-key",
    "FM-FORBIDDEN-KEY": "frontmatter.forbidden-key",
    "FM-BAD-TYPE": "frontmatter.bad-type",
    "FM-BAD-DATE": "frontmatter.bad-date",
    "FM-BAD-ID": "frontmatter.bad-id",
    "FM-BAD-CATEGORY": "frontmatter.bad-category",
    "FM-BAD-TAG": "frontmatter.bad-tag",
    "FM-BAD-SCOPE": "frontmatter.bad-scope",
    "FM-BAD-CADENCE": "frontmatter.bad-cadence",
    "BODY-BAD-H1": "render.bad-h1",
    "BODY-BAD-TASK-NAME": "render.bad-task-name",
    "BODY-MISSING-SECTION": "render.missing-section",
    "BODY-SECTION-ORDER": "render.section-order",
    "BODY-MISSING-PART-OF": "render.missing-part-of",
    "BODY-MISSING-PREVIOUS": "render.missing-previous",
    "BODY-FORBIDDEN-PREVIOUS": "render.forbidden-previous",
    "BODY-MISSING-OUTCOME": "render.missing-outcome",
}


@dataclass(frozen=True)
class Finding:
    """One validation failure. `code` is dotted "<area>.<problem>" (bytes.*,
    path.*, frontmatter.*, render.*, invariant.*) and is stable for scripts."""

    path: Path
    code: str
    message: str

    def __str__(self):
        return f"{self.path}: {self.code}: {self.message}"


@dataclass
class _ParentScan:
    """What the directory walk found for one parent: its index card (may be
    missing) and run files keyed by run number."""

    parent: str
    directory: Path
    index: Path | None = None
    runs: dict = field(default_factory=dict)


def validate_vault(vault_path):
    """Every finding for the whole vault, sorted. Walks the root and category
    directories, checks each parent, then the cross-cutting rules (stem
    collisions, git attributes and committed bytes)."""
    vault = Path(vault_path)
    if not vault.is_dir():
        return [Finding(vault, "path.missing-vault", "the vault directory does not exist")]
    findings = []
    stems = {}
    categories = {}
    for entry in _entries(vault):
        if entry.is_dir():
            if entry.name in VAULT_DIRS:
                continue
            code = cards.DIRECTORIES.get(entry.name)
            if code is None:
                findings.append(
                    Finding(
                        entry,
                        "path.unknown-category-dir",
                        f"{entry.name} is not one of the category directories "
                        f"{', '.join(sorted(cards.DIRECTORIES))}",
                    )
                )
                continue
            categories[code] = _scan_category(entry, code, findings, stems)
        elif entry.name not in ROOT_FILES and entry.name not in OS_ARTIFACTS:
            # vault-spec 3 lists these as root contents. The exemption stays
            # here rather than in _stray_file, which _scan_category also calls:
            # baseline/.gitignore is still a violation.
            _stray_file(entry, findings, stems)
    for code in sorted(categories):
        _check_parent_numbers(vault, code, categories[code], findings)
        for scan in categories[code]:
            _check_parent(scan, findings)
    findings.extend(_stem_collisions(stems))
    _check_git(vault, _card_paths(categories), findings)
    return _ordered(findings)


def _card_paths(categories):
    paths = []
    for scans in categories.values():
        for scan in scans:
            if scan.index is not None:
                paths.append(scan.index)
            paths.extend(scan.runs[number] for number in sorted(scan.runs))
    return paths


def _check_git(vault, card_paths, findings):
    """vault-spec 3 and 8: what git records, and what it is allowed to hide.

    Silent on a tree that is not a repository, because every rule here is a
    statement about a repository. validate_parent_dir does not run these: they
    are properties of the vault, not of one card.
    """
    if not vaultmod.is_repo(vault):
        return

    attributes = vault / ".gitattributes"
    if not attributes.is_file():
        findings.append(
            Finding(
                attributes,
                "path.missing-gitattributes",
                "the vault root needs '* text=auto eol=lf'; without it a Windows "
                "checkout records CRLF",
            )
        )
    elif card_paths:
        for path in card_paths:
            attrs = vaultmod.text_attributes(vault, [path]).get(
                str(path.relative_to(vault).as_posix()), {}
            )
            if attrs.get("text") in ("auto", "set") and attrs.get("eol") == "lf":
                continue
            findings.append(
                Finding(
                    path,
                    "bytes.crlf-permitted",
                    "the git attributes of this card do not force LF on check-in "
                    f"(text={attrs.get('text', 'unspecified')}, "
                    f"eol={attrs.get('eol', 'unspecified')})",
                )
            )

    for name in sorted(vaultmod.ignored(vault, card_paths)):
        findings.append(
            Finding(
                vault / name,
                "path.gitignore-hides-card",
                "a .gitignore hides this card, so it can never be committed",
            )
        )

    for name, data in vaultmod.tracked_blobs(vault):
        carriage = data.find(b"\r")
        if carriage >= 0:
            findings.append(
                Finding(
                    vault / name,
                    "bytes.crlf-committed",
                    f"the committed blob has a carriage return at line "
                    f"{_line(data, carriage)}; what a remote receives must be LF",
                )
            )


def validate_parent_dir(vault_path, parent_id):
    """Findings for one parent directory only; used by `hunt new`/`hunt run`
    before committing. Skips the vault-wide git checks (see _check_git)."""
    vault = Path(vault_path)
    directory = cards.parent_dir(vault, parent_id)
    if not directory.is_dir():
        return [
            Finding(directory, "path.missing-parent-dir", f"{parent_id} has no directory")
        ]
    findings = []
    stems = {}
    scan = _scan_parent(directory, parent_id, findings, stems)
    _check_parent(scan, findings)
    findings.extend(_stem_collisions(stems))
    return _ordered(findings)


def _entries(directory):
    return sorted(directory.iterdir(), key=lambda entry: entry.name)


def _scan_category(directory, code, findings, stems):
    """Walk one category directory; every well-named subdirectory becomes a
    _ParentScan, everything else a path.* finding."""
    scans = []
    for entry in _entries(directory):
        if not entry.is_dir():
            if entry.name not in OS_ARTIFACTS:
                _stray_file(entry, findings, stems)
            continue
        match = cards.PARENT_RE.fullmatch(entry.name)
        named = match is not None and match.group("category") == code
        if not named or int(match.group("number")) < 1:
            findings.append(
                Finding(
                    entry,
                    "path.bad-parent-dir",
                    f"a directory here is named {code}-NNN with a 3-digit number from 001",
                )
            )
            continue
        scans.append(_scan_parent(entry, entry.name, findings, stems))
    return scans


def _scan_parent(directory, parent, findings, stems):
    scan = _ParentScan(parent, directory)
    for entry in _entries(directory):
        if entry.is_dir():
            if cards.PARENT_RE.fullmatch(entry.name) is not None:
                message = "a parent directory lives directly under its category directory"
            else:
                message = "a parent directory holds card files and nothing else"
            findings.append(Finding(entry, "path.bad-parent-dir", message))
            continue
        name = entry.name
        if name in OS_ARTIFACTS:
            continue
        if not name.endswith(".md"):
            findings.append(
                Finding(
                    entry,
                    "path.stray-file",
                    "a parent directory holds card files and nothing else",
                )
            )
            continue
        stem = name[:-3]
        _note_stem(stems, entry)
        if stem == parent:
            scan.index = entry
            continue
        match = cards.RUN_RE.fullmatch(stem)
        number = int(match.group("number")) if match is not None else 0
        if number > 0 and match.group("parent") == parent:
            scan.runs[number] = entry
        elif stem.startswith(parent + "."):
            findings.append(
                Finding(
                    entry,
                    "path.bad-run-filename",
                    f"a run file is named {parent}.NNN.md with a 3-digit number from 001",
                )
            )
        else:
            findings.append(
                Finding(
                    entry,
                    "path.stray-markdown",
                    f"only the index and runs of {parent} may live in this directory",
                )
            )
    if scan.index is None:
        findings.append(
            Finding(
                directory / cards.card_filename(parent),
                "path.missing-index",
                f"{parent} has no index card",
            )
        )
    return scan


def _stray_file(entry, findings, stems):
    if entry.name.endswith(".md"):
        _note_stem(stems, entry)
        findings.append(
            Finding(
                entry,
                "path.stray-markdown",
                "a card file lives only inside a parent directory",
            )
        )
    else:
        findings.append(
            Finding(
                entry,
                "path.stray-file",
                "only card files may live under the vault root, outside .git, .github and .obsidian",
            )
        )


def _note_stem(stems, path):
    """Record a .md file under its case-folded stem for _stem_collisions."""
    stems.setdefault(path.name[:-3].lower(), []).append(path)


def _stem_collisions(stems):
    findings = []
    for paths in stems.values():
        if len(paths) < 2:
            continue
        names = ", ".join(sorted(path.name for path in paths))
        for path in paths:
            findings.append(
                Finding(
                    path,
                    "path.stem-collision",
                    f"filename stems are unique across the vault, case aside: {names}",
                )
            )
    return findings


def _check_parent_numbers(vault, code, scans, findings):
    numbers = sorted(cards.parse_parent_id(scan.parent).number for scan in scans)
    if not numbers:
        return
    present = set(numbers)
    missing = [number for number in range(1, numbers[-1] + 1) if number not in present]
    if missing:
        findings.append(
            Finding(
                cards.category_dir(vault, code),
                "invariant.number-gap",
                "parent numbers must run from 001 with no gaps; missing "
                + ", ".join(f"{code}-{number:03d}" for number in missing),
            )
        )


def _check_parent(scan, findings):
    """All per-parent checks. The index is re-rendered against the parsed runs,
    so if any run failed to parse (`usable` false) the index render comparison
    is skipped rather than reported as a spurious mismatch."""
    runs = []
    usable = True
    for number in sorted(scan.runs):
        run = _check_run_file(scan.runs[number], scan.parent, findings)
        if run is None:
            usable = False
        else:
            runs.append((number, run))
    if scan.index is not None:
        _check_index_file(scan, [run for _, run in runs] if usable else None, findings)
    _check_chain(scan, runs, findings)
    _check_numbering(scan, findings)
    _check_open_runs(scan, runs, findings)


def _check_run_file(path, parent, findings):
    """bytes -> links -> frontmatter -> parse -> re-render, stopping at the
    first stage that fails so later stages do not pile on derived noise."""
    text = _read_text(path, findings)
    if text is None:
        return None
    _check_links(path, text, parent, findings)
    if _check_frontmatter(path, text, parent, False, findings) is None:
        return None
    run = _parse(path, text, False, findings)
    if run is None:
        return None
    rendered = _render(path, cards.render_run, findings, run)
    if rendered is not None:
        _compare(path, text, rendered, findings)
    return run


def _check_index_file(scan, runs, findings):
    path = scan.index
    text = _read_text(path, findings)
    if text is None:
        return
    _check_links(path, text, scan.parent, findings)
    if _check_frontmatter(path, text, scan.parent, True, findings) is None:
        return
    parent = _parse(path, text, True, findings)
    if parent is None or runs is None:
        return
    rendered = _render(path, cards.render_parent, findings, parent, runs)
    if rendered is not None:
        _compare(path, text, rendered, findings)


def _read_text(path, findings):
    """Decode a card, or return None after recording byte-level findings."""
    data = path.read_bytes()
    before = len(findings)
    _check_bytes(path, data, findings)
    if len(findings) != before:
        return None
    return data.decode("utf-8")


def _check_bytes(path, data, findings):
    """card-spec 3.1 byte rules: ASCII only, no control bytes, LF endings, one
    trailing newline, no trailing spaces. Each problem is reported once, at
    its first occurrence."""
    if not data:
        findings.append(Finding(path, "bytes.empty-file", "the file is empty"))
        return
    wide = None
    control = None
    for offset, byte in enumerate(data):
        if byte >= 0x80:
            if wide is None:
                wide = offset
        elif (byte < 0x20 and byte not in (0x0A, 0x0D)) or byte == 0x7F:
            if control is None:
                control = offset
        if wide is not None and control is not None:
            break
    if wide is not None:
        findings.append(
            Finding(
                path,
                "bytes.non-ascii",
                f"non-ASCII byte 0x{data[wide]:02x} at line {_line(data, wide)}",
            )
        )
    if control is not None:
        findings.append(
            Finding(
                path,
                "bytes.control-character",
                f"forbidden byte 0x{data[control]:02x} at line {_line(data, control)}",
            )
        )
    carriage = data.find(b"\r")
    if carriage >= 0:
        findings.append(
            Finding(
                path,
                "bytes.crlf",
                f"carriage return at line {_line(data, carriage)}; line endings are LF only",
            )
        )
    if data[-1] != 0x0A:
        findings.append(
            Finding(
                path,
                "bytes.no-trailing-newline",
                "the file does not end with a newline",
            )
        )
    elif data.endswith(b"\n\n"):
        findings.append(
            Finding(path, "bytes.extra-trailing-newline", "the file ends with a blank line")
        )
    for number, line in enumerate(data.split(b"\n"), start=1):
        if line.endswith(b" "):
            findings.append(
                Finding(
                    path,
                    "bytes.trailing-whitespace",
                    f"trailing space at line {number}",
                )
            )
            break


def _line(data, offset):
    """1-based line number of a byte offset."""
    return data.count(b"\n", 0, offset) + 1


def _check_frontmatter(path, text, parent, is_index, findings):
    before = len(findings)
    try:
        block, _ = cards.split_frontmatter(text)
        keys = cards.frontmatter_key_order(text)
    except cards.CardError as exc:
        findings.append(_card_error(path, exc))
        return None
    try:
        data = cards.load_frontmatter(block)
    except cards.CardError as exc:
        findings.append(_card_error(path, exc))
        return None
    allowed = cards.PARENT_KEYS if is_index else cards.RUN_KEYS
    required = cards.PARENT_REQUIRED_KEYS if is_index else cards.RUN_REQUIRED_KEYS
    _check_keys(path, keys, data, allowed, required, findings)
    _check_values(path, data, parent, is_index, findings)
    if len(findings) != before:
        return None
    return data


def _check_keys(path, keys, data, allowed, required, findings):
    """Closed schema: no duplicates, no forbidden or unknown keys, all required
    keys present, and the present keys in the canonical order. `keys` is the
    textual order (frontmatter_key_order), `data` the loaded mapping."""
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        findings.append(
            Finding(
                path,
                "frontmatter.duplicate-key",
                "keys appear more than once: " + ", ".join(duplicates),
            )
        )
    names = list(dict.fromkeys(keys))
    for key in data:
        name = key if isinstance(key, str) else str(key)
        if name not in names:
            names.append(name)
    forbidden = [name for name in names if name in cards.FORBIDDEN_KEYS]
    if forbidden:
        findings.append(
            Finding(
                path,
                "frontmatter.forbidden-key",
                ", ".join(forbidden) + " must not appear in frontmatter",
            )
        )
    unknown = [
        name for name in names if name not in allowed and name not in cards.FORBIDDEN_KEYS
    ]
    if unknown:
        findings.append(
            Finding(
                path,
                "frontmatter.unknown-key",
                "the schema is closed; unknown keys: " + ", ".join(unknown),
            )
        )
    missing = [name for name in required if name not in data]
    if missing:
        findings.append(
            Finding(
                path,
                "frontmatter.missing-key",
                "missing required keys: " + ", ".join(missing),
            )
        )
    present = [name for name in dict.fromkeys(keys) if name in allowed]
    expected = [name for name in allowed if name in present]
    if present != expected:
        findings.append(
            Finding(
                path,
                "frontmatter.key-order",
                "keys must read " + ", ".join(expected)
                + "; they read " + ", ".join(present),
            )
        )


def _check_values(path, data, parent, is_index, findings):
    """Per-key value checks, plus consistency with the filename stem and the
    containing parent directory."""
    stem = path.name[:-3]
    if "id" in data:
        value = data["id"]
        valid = cards.is_valid_parent_id(value) if is_index else cards.is_valid_run_id(value)
        kind = "parent" if is_index else "run"
        if not valid:
            findings.append(
                Finding(
                    path,
                    "frontmatter.bad-id",
                    f"id {_show(value)} is not a well-formed {kind} ID",
                )
            )
        elif value != stem:
            findings.append(
                Finding(
                    path,
                    "frontmatter.id-path-mismatch",
                    f"id {value} does not match the filename stem {stem}",
                )
            )
    if is_index:
        _check_category(path, data, parent, findings)
        _check_tags(path, data, findings)
    elif "parent" in data:
        value = data["parent"]
        if not cards.is_valid_parent_id(value):
            findings.append(
                Finding(
                    path,
                    "frontmatter.bad-parent-ref",
                    f"parent {_show(value)} is not a well-formed parent ID",
                )
            )
        elif value != parent:
            findings.append(
                Finding(
                    path,
                    "frontmatter.bad-parent-ref",
                    f"parent {value} does not match the containing directory {parent}",
                )
            )
    if not is_index and "scope" in data:
        _check_scope(path, data, findings)
    if is_index and "cadence" in data:
        _check_cadence(path, data, findings)
    if "status" in data:
        value = data["status"]
        statuses = cards.PARENT_STATUSES if is_index else cards.RUN_STATUSES
        if not isinstance(value, str) or value not in statuses:
            findings.append(
                Finding(
                    path,
                    "frontmatter.bad-status",
                    f"status {_show(value)} is not one of " + ", ".join(statuses),
                )
            )
    for key in ("run_date", "latest_run_date"):
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, datetime.date):
            findings.append(
                Finding(
                    path,
                    "frontmatter.unquoted-date",
                    f"{key} must be quoted; YAML read it as a date value",
                )
            )
        elif not isinstance(value, str):
            findings.append(
                Finding(
                    path,
                    "frontmatter.bad-type",
                    f"{key} must be a quoted YYYY-MM-DD string",
                )
            )
        elif not cards.is_valid_date(value):
            findings.append(
                Finding(
                    path,
                    "frontmatter.bad-date",
                    f"{key} {_show(value)} is not a valid YYYY-MM-DD date",
                )
            )
    for key in ("latest_run", "previous_run"):
        if key in data and not cards.is_valid_run_id(data[key]):
            findings.append(
                Finding(
                    path,
                    "frontmatter.bad-run-ref",
                    f"{key} {_show(data[key])} is not a well-formed run ID",
                )
            )


def _check_category(path, data, parent, findings):
    if "category" not in data:
        return
    value = data["category"]
    if not isinstance(value, str) or value not in cards.CATEGORIES:
        findings.append(
            Finding(
                path,
                "frontmatter.bad-category",
                f"category {_show(value)} is not one of "
                + ", ".join(sorted(cards.CATEGORIES)),
            )
        )
        return
    expected = cards.parse_parent_id(parent).category
    if value != expected:
        findings.append(
            Finding(
                path,
                "frontmatter.bad-category",
                f"category {value} does not match {expected}, the code of this "
                "card's ID and of its directory",
            )
        )


def _check_tags(path, data, findings):
    if "tags" not in data:
        return
    value = data["tags"]
    if not isinstance(value, list) or not all(isinstance(tag, str) for tag in value):
        message = "tags must be a list of strings"
        findings.append(Finding(path, "frontmatter.bad-type", message))
        return
    bad = [tag for tag in value if not cards.is_valid_tag(tag)]
    if bad:
        findings.append(
            Finding(
                path,
                "frontmatter.bad-tag",
                "tags match ^[a-z0-9][a-z0-9_-]*$; these do not: "
                + ", ".join(_show(tag) for tag in bad),
            )
        )


def _check_scope(path, data, findings):
    """card-spec 6.1: scope is free text, so only its shape is checked here.
    No value set exists, and inventing one in the validator would be exactly
    the enforcement the spec withholds. A v5 scalar is still accepted."""
    value = data["scope"]
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        findings.append(
            Finding(
                path,
                "frontmatter.bad-type",
                "scope must be a list of quoted strings, or one quoted string",
            )
        )
        return
    if not cards.is_valid_scope_list(items):
        findings.append(
            Finding(
                path,
                "frontmatter.bad-scope",
                f"scope {_show(value)} must be one or more items, each a single "
                "non-empty line of printable ASCII, without a double quote, a "
                "backslash, or surrounding spaces",
            )
        )


def _check_cadence(path, data, findings):
    value = data["cadence"]
    if not isinstance(value, int) or isinstance(value, bool):
        findings.append(
            Finding(path, "frontmatter.bad-type", "cadence must be an unquoted integer")
        )
        return
    if not cards.is_valid_cadence(value):
        findings.append(
            Finding(
                path,
                "frontmatter.bad-cadence",
                f"cadence {_show(value)} must be a positive integer number of days",
            )
        )


def _check_links(path, text, parent, findings):
    """card-spec link rules: no aliases, targets are bare IDs, and a link into
    another task points at its parent index rather than one of its runs."""
    aliases = sorted(set(cards.find_alias_links(text)))
    if aliases:
        findings.append(
            Finding(
                path,
                "invariant.link-alias",
                "aliased links are forbidden in card files: " + ", ".join(aliases),
            )
        )
    outside = []
    malformed = []
    for raw in cards.find_links(text):
        target = raw.split("|", 1)[0].split("#", 1)[0].strip()
        if cards.is_valid_parent_id(target):
            continue
        if cards.is_valid_run_id(target):
            if cards.parse_run_id(target).parent != parent:
                outside.append(target)
            continue
        malformed.append(target)
    if outside:
        findings.append(
            Finding(
                path,
                "invariant.link-direction",
                "a link to another task targets its parent index, never a run: "
                + ", ".join(sorted(set(outside))),
            )
        )
    if malformed:
        findings.append(
            Finding(
                path,
                "invariant.link-target",
                "a link target is a bare parent or run ID; these are not: "
                + ", ".join(_show(target) for target in sorted(set(malformed))),
            )
        )


def _parse(path, text, is_index, findings):
    parser = cards.parse_parent if is_index else cards.parse_run
    try:
        return parser(text)
    except cards.CardError as exc:
        findings.append(_card_error(path, exc))
        return None


def _render(path, renderer, findings, *args):
    try:
        return renderer(*args)
    except cards.CardError as exc:
        findings.append(_card_error(path, exc))
        return None


def _compare(path, text, rendered, findings):
    """Report the first differing line between the card and its re-render."""
    if text == rendered:
        return
    found = text.split("\n")
    expected = rendered.split("\n")
    for index in range(max(len(found), len(expected))):
        got = found[index] if index < len(found) else None
        want = expected[index] if index < len(expected) else None
        if got == want:
            continue
        findings.append(
            Finding(
                path,
                "render.mismatch",
                f"line {index + 1}: expected {_show(want)}, found {_show(got)}",
            )
        )
        return


def _check_chain(scan, runs, findings):
    """previous_run must point at the run numbered one lower (none for 001)."""
    for number, run in runs:
        expected = None if number == 1 else cards.run_id(scan.parent, number - 1)
        actual = run.previous_run
        if actual == expected:
            continue
        if expected is None:
            message = f"run 001 has no predecessor; previous_run is {actual}"
        elif actual is None:
            message = f"previous_run must be {expected}; it is absent"
        else:
            message = f"previous_run must be {expected}; it is {actual}"
        findings.append(Finding(scan.runs[number], "invariant.chain-broken", message))


def _check_numbering(scan, findings):
    if not scan.runs:
        return
    missing = [number for number in range(1, max(scan.runs) + 1) if number not in scan.runs]
    if missing:
        findings.append(
            Finding(
                scan.directory,
                "invariant.number-gap",
                "run numbers must run from 001 with no gaps; missing "
                + ", ".join(f"{number:03d}" for number in missing),
            )
        )


def _check_open_runs(scan, runs, findings):
    open_runs = sorted(run.id for _, run in runs if run.status == cards.STATUS_OPEN)
    if len(open_runs) > 1:
        findings.append(
            Finding(
                scan.directory,
                "invariant.multiple-open",
                "a parent has at most one open run; these are open: " + ", ".join(open_runs),
            )
        )


def _card_error(path, exc):
    return Finding(path, _CARD_ERROR_CODES.get(exc.code, "render.parse-error"), _brief(exc))


def _brief(value):
    """Collapse whitespace in an exception message to one line of ASCII."""
    return _ascii(" ".join(str(value).split()))


def _show(value):
    """repr() of a value for a message, ASCII-escaped and length-capped."""
    if value is None:
        return "end of file"
    text = _ascii(repr(value))
    if len(text) > _QUOTE_LIMIT:
        text = text[: _QUOTE_LIMIT - 3] + "..."
    return text


def _ascii(text):
    """Escape non-ASCII so findings are safe to print anywhere."""
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _ordered(findings):
    """Deterministic output order: by path, then code, then message."""
    def key(finding):
        return (str(finding.path), finding.code, finding.message)

    return sorted(findings, key=key)


# --- transition validation (card-spec 8.2) -----------------------------------

# 8.2 is 8.1 plus invariants 7-10 of Section 7: what a proposed tree may do to
# the accepted tree it would replace. None of those are visible in a single
# tree, which is why validate_vault cannot report any of them.
_RUN_STATUS_ORDER = {status: index for index, status in enumerate(cards.RUN_STATUSES)}


def validate_transition(vault_path, revision):
    """Findings for the working tree, read as a proposed tree, against the
    accepted tree recorded at `revision`. Snapshot findings are not repeated
    here; the CLI runs validate_vault as well."""
    vault = Path(vault_path)
    findings = []
    accepted = _revision_cards(vault, revision)
    proposed = _tree_cards(vault)
    for name in sorted(accepted):
        path = vault / name
        if name not in proposed:
            findings.append(
                Finding(
                    path,
                    "transition.card-deleted",
                    f"{name} is recorded at {revision} but not in the tree under "
                    "review; an accepted card is never deleted, renamed, or moved",
                )
            )
            continue
        is_index = name.rsplit("/", 1)[1][:-3] == name.split("/")[1]
        try:
            if is_index:
                before = cards.parse_parent(accepted[name])
                after = cards.parse_parent(proposed[name])
                found = _check_parent_transition(path, revision, before, after)
            else:
                before = cards.parse_run(accepted[name])
                after = cards.parse_run(proposed[name])
                found = _check_run_transition(path, revision, before, after)
        except cards.CardError:
            # A card that does not parse, or whose fields do not validate, is
            # already a snapshot finding. The checks run inside this guard so
            # that a field validating lazily -- latest_run and latest_run_date
            # are the two parse_parent never touches -- skips the whole card
            # rather than escaping with half of it reported.
            continue
        findings.extend(found)
    return _ordered(findings)


def _revision_cards(vault, revision):
    """{vault-relative path: text} for the card files a revision records."""
    accepted = {}
    for name, data in vaultmod.tracked_blobs(vault, revision):
        if not _is_card_name(name):
            continue
        try:
            accepted[name] = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return accepted


def _tree_cards(vault):
    """The same mapping for the working tree. Symlinks are skipped: a
    comparison must not follow one out of the vault."""
    proposed = {}
    for directory in sorted(cards.DIRECTORIES):
        category = vault / directory
        if not category.is_dir() or category.is_symlink():
            continue
        for parent_dir in sorted(category.iterdir()):
            if not parent_dir.is_dir() or parent_dir.is_symlink():
                continue
            for path in sorted(parent_dir.glob("*.md")):
                if path.is_symlink() or not path.is_file():
                    continue
                name = f"{directory}/{parent_dir.name}/{path.name}"
                if not _is_card_name(name):
                    continue
                try:
                    proposed[name] = cards.read_card(path)
                except cards.CardError:
                    continue
    return proposed


def _is_card_name(name):
    """<category dir>/<PARENT>/<PARENT>.md or <PARENT>.<NNN>.md, and nothing
    else: only those are cards, and only cards carry invariants."""
    parts = name.split("/")
    if len(parts) != 3 or parts[0] not in cards.DIRECTORIES:
        return False
    if not parts[2].endswith(".md"):
        return False
    stem = parts[2][:-3]
    if stem == parts[1]:
        return cards.is_valid_parent_id(stem)
    return cards.is_valid_run_id(stem) and stem.split(".")[0] == parts[1]


def _check_parent_transition(path, revision, before, after):
    """card-spec 7, invariants 7, 9 and 10 for one parent index card."""
    findings = []
    if after.name != before.name:
        findings.append(
            Finding(
                path,
                "transition.number-reused",
                f"{before.id} names a different task than the one accepted at "
                f"{revision} ({_show(before.name)} -> {_show(after.name)}); an "
                "accepted number is never reused",
            )
        )
    if after.tags != before.tags:
        findings.append(
            Finding(
                path,
                "transition.field-changed",
                f"tags changed since {revision}; on an accepted parent only "
                "status, cadence and the latest_run pair may change",
            )
        )
    if after.category != before.category:
        findings.append(
            Finding(
                path,
                "transition.field-changed",
                f"category changed since {revision}; on an accepted parent only "
                "status, cadence and the latest_run pair may change",
            )
        )
    if before.status == cards.STATUS_RETIRED and after.status == cards.STATUS_ACTIVE:
        findings.append(
            Finding(
                path,
                "transition.status-reverted",
                f"status went from retired back to active since {revision}; "
                "retirement is one-way",
            )
        )
    if before.status == cards.STATUS_RETIRED and (
        after.latest_run != before.latest_run
        or after.latest_run_date != before.latest_run_date
    ):
        findings.append(
            Finding(
                path,
                "transition.retirement-freeze-broken",
                f"latest_run or latest_run_date changed on a card already retired "
                f"at {revision}; retirement freezes both",
            )
        )
    if before.latest_run is not None and after.latest_run is None:
        findings.append(
            Finding(
                path,
                "transition.field-changed",
                f"latest_run was removed since {revision}; it only ever advances "
                "to a newly added run",
            )
        )
    elif (
        before.latest_run is not None
        and after.latest_run is not None
        and _run_number(after.latest_run) < _run_number(before.latest_run)
    ):
        findings.append(
            Finding(
                path,
                "transition.field-changed",
                f"latest_run moved back from {before.latest_run} to "
                f"{after.latest_run} since {revision}; it only ever advances",
            )
        )
    return findings


def _check_run_transition(path, revision, before, after):
    """card-spec 7, invariant 9 for one run card: only status advances, and the
    Outcome may only be appended to."""
    findings = []
    for field, was, now in (
        ("id", before.id, after.id),
        ("parent", before.parent, after.parent),
        ("run_date", before.run_date, after.run_date),
        ("previous_run", before.previous_run, after.previous_run),
        ("scope", before.scope, after.scope),
    ):
        if now != was:
            findings.append(
                Finding(
                    path,
                    "transition.field-changed",
                    f"{field} changed since {revision} ({_show(was)} -> "
                    f"{_show(now)}); on an accepted run only status may change",
                )
            )
    was = _RUN_STATUS_ORDER.get(before.status)
    now = _RUN_STATUS_ORDER.get(after.status)
    if was is not None and now is not None and now not in (was, was + 1):
        findings.append(
            Finding(
                path,
                "transition.bad-status-transition",
                f"status went from {before.status} to {after.status} since "
                f"{revision}; it advances one step along "
                + " -> ".join(cards.RUN_STATUSES),
            )
        )
    if not after.outcome.startswith(before.outcome):
        findings.append(
            Finding(
                path,
                "transition.outcome-changed",
                f"the Outcome accepted at {revision} was rewritten rather than "
                "appended to",
            )
        )
    return findings


def _run_number(value):
    """The run number in an id, or 0 when it is not a run id at all (which is a
    snapshot finding, not this function's business)."""
    try:
        return cards.parse_run_id(value).number
    except cards.CardError:
        return 0
