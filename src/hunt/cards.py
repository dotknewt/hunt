from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import yaml

from . import HuntError

CATEGORIES = {"BSL": "baseline", "HNT": "hunt", "MTH": "math"}
DIRECTORIES = {directory: code for code, directory in CATEGORIES.items()}

MAX_NUMBER = 999

STATUS_ACTIVE = "active"
STATUS_RETIRED = "retired"
STATUS_OPEN = "open"
STATUS_COMPLETE = "complete"
STATUS_VOID = "void"

PARENT_STATUSES = (STATUS_ACTIVE, STATUS_RETIRED)
RUN_STATUSES = (STATUS_OPEN, STATUS_COMPLETE, STATUS_VOID)

PARENT_KEYS = ("id", "category", "tags", "status", "latest_run", "latest_run_date")
PARENT_REQUIRED_KEYS = ("id", "category", "tags", "status")
RUN_KEYS = ("id", "parent", "run_date", "previous_run", "status", "scope")
RUN_REQUIRED_KEYS = ("id", "parent", "run_date", "status")
FORBIDDEN_KEYS = ("run_number",)

WHY = "Why"
LATEST_FINDINGS = "Latest findings"
RUN_HISTORY = "Run history"
OUTCOME = "Outcome"
PARENT_SECTIONS = (WHY, LATEST_FINDINGS, RUN_HISTORY)

_CODES = "|".join(CATEGORIES)
PARENT_RE = re.compile(rf"(?P<category>{_CODES})-(?P<number>[0-9]{{3}})")
RUN_RE = re.compile(
    rf"(?P<parent>(?:{_CODES})-[0-9]{{3}})\.(?P<number>[0-9]{{3}})"
)
TAG_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
# card-spec 4: scope is free text. The grammar below is hygiene, not a value
# set: printable ASCII, no quote or backslash, so the renderer can emit the
# value inside double quotes with no escaping and re-read it byte for byte.
SCOPE_RE = re.compile(r'[ -!#-\[\]-~]+')
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

_FENCE = "---\n"
_HEADING_RE = re.compile(r"^(#{2,6}) (.+)$")
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*):(?: |$)")
_ALIAS_RE = re.compile(r"\[\[[^\[\]|]*\|[^\[\]]*\]\]")
_LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")


class CardError(HuntError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class ParentId(NamedTuple):
    category: str
    number: int


class RunId(NamedTuple):
    parent: str
    number: int


@dataclass
class Parent:
    frontmatter: dict
    name: str = ""
    why: str = ""
    extra: str = ""

    @property
    def id(self):
        return _string(self.frontmatter, "id")

    @property
    def category(self):
        return _string(self.frontmatter, "category")

    @property
    def tags(self):
        if "tags" not in self.frontmatter:
            raise CardError("frontmatter is missing tags", "FM-MISSING-KEY")
        value = self.frontmatter["tags"]
        if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
            raise CardError("tags must be a list of strings", "FM-BAD-TYPE")
        return list(value)

    @property
    def status(self):
        return _string(self.frontmatter, "status")

    @property
    def latest_run(self):
        return _optional_string(self.frontmatter, "latest_run")

    @property
    def latest_run_date(self):
        return _optional_date(self.frontmatter, "latest_run_date")


@dataclass
class Run:
    frontmatter: dict
    outcome: str = ""
    extra: str = ""

    @property
    def id(self):
        return _string(self.frontmatter, "id")

    @property
    def parent(self):
        return _string(self.frontmatter, "parent")

    @property
    def run_date(self):
        if "run_date" not in self.frontmatter:
            raise CardError("frontmatter is missing run_date", "FM-MISSING-KEY")
        return _date_text(self.frontmatter["run_date"], "run_date")

    @property
    def previous_run(self):
        return _optional_string(self.frontmatter, "previous_run")

    @property
    def status(self):
        return _string(self.frontmatter, "status")

    @property
    def scope(self):
        if "scope" not in self.frontmatter:
            return None
        value = self.frontmatter["scope"]
        if not isinstance(value, str):
            raise CardError("scope must be a string", "FM-BAD-TYPE")
        if not is_valid_scope(value):
            raise CardError(f"{value!r} is not a valid scope", "FM-BAD-SCOPE")
        return value


def _string(frontmatter, key):
    if key not in frontmatter:
        raise CardError(f"frontmatter is missing {key}", "FM-MISSING-KEY")
    value = frontmatter[key]
    if not isinstance(value, str):
        raise CardError(f"{key} must be a string", "FM-BAD-TYPE")
    return value


def _optional_string(frontmatter, key):
    if key not in frontmatter:
        return None
    return _string(frontmatter, key)


def _optional_date(frontmatter, key):
    if key not in frontmatter:
        return None
    return _date_text(frontmatter[key], key)


def _date_text(value, key):
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise CardError(f"{key} must be a YYYY-MM-DD string", "FM-BAD-TYPE")


def _fields(card, keys):
    for key in keys:
        getattr(card, key)


def is_valid_tag(value):
    return isinstance(value, str) and TAG_RE.fullmatch(value) is not None


def is_valid_scope(value):
    if not isinstance(value, str) or value != value.strip():
        return False
    return SCOPE_RE.fullmatch(value) is not None


def is_valid_date(value):
    if not isinstance(value, str) or DATE_RE.fullmatch(value) is None:
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def is_valid_task_name(value):
    try:
        _check_name(value)
    except CardError:
        return False
    return True


def is_valid_parent_id(value):
    try:
        parse_parent_id(value)
    except CardError:
        return False
    return True


def is_valid_run_id(value):
    try:
        parse_run_id(value)
    except CardError:
        return False
    return True


def load_frontmatter(block):
    """The one frontmatter loader: rejects duplicate keys and keeps an unquoted
    date a date object so callers can report it."""
    return _load_frontmatter(block)


def find_links(text):
    return [raw for raw in _LINK_RE.findall(text)]


def find_alias_links(text):
    return _ALIAS_RE.findall(text)


def resolve_category(value):
    if isinstance(value, str):
        code = value.upper()
        if code in CATEGORIES:
            return code
        directory = value.lower()
        if directory in DIRECTORIES:
            return DIRECTORIES[directory]
    raise CardError(f"{value!r} is not a known category", "FM-BAD-CATEGORY")


def parent_id(category_code, number):
    code = resolve_category(category_code)
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise CardError(f"{number!r} is not a card number", "FM-BAD-ID")
    if number > MAX_NUMBER:
        raise CardError(f"number {number} exceeds {MAX_NUMBER}", "NUMBER-OVERFLOW")
    return f"{code}-{number:03d}"


def run_id(parent, number):
    parse_parent_id(parent)
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise CardError(f"{number!r} is not a run number", "FM-BAD-ID")
    if number > MAX_NUMBER:
        raise CardError(f"number {number} exceeds {MAX_NUMBER}", "NUMBER-OVERFLOW")
    return f"{parent}.{number:03d}"


def parse_parent_id(value):
    match = PARENT_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise CardError(f"{value!r} is not a parent ID", "FM-BAD-ID")
    number = int(match.group("number"))
    if number < 1:
        raise CardError(f"{value!r} numbers from zero", "FM-BAD-ID")
    return ParentId(match.group("category"), number)


def parse_run_id(value):
    match = RUN_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise CardError(f"{value!r} is not a run ID", "FM-BAD-ID")
    number = int(match.group("number"))
    if number < 1:
        raise CardError(f"{value!r} numbers from zero", "FM-BAD-ID")
    return RunId(match.group("parent"), number)


def card_filename(ident):
    return f"{ident}.md"


def category_dir(vault_path, category_code):
    return Path(vault_path) / CATEGORIES[resolve_category(category_code)]


def parent_dir(vault_path, parent):
    ident = parse_parent_id(parent)
    return category_dir(vault_path, ident.category) / parent


def parent_path(vault_path, parent):
    return parent_dir(vault_path, parent) / card_filename(parent)


def run_path(vault_path, run):
    ident = parse_run_id(run)
    return parent_dir(vault_path, ident.parent) / card_filename(run)


def run_number_from_filename(path):
    name = Path(path).name
    match = RUN_RE.fullmatch(name[:-3]) if name.endswith(".md") else None
    if match is None:
        raise CardError(f"{name!r} is not a run filename", "LAYOUT-BAD-RUN-FILENAME")
    number = int(match.group("number"))
    if number < 1:
        raise CardError(f"{name!r} numbers from zero", "LAYOUT-BAD-RUN-FILENAME")
    return number


def next_parent_number(vault_path, category_code):
    code = resolve_category(category_code)
    directory = category_dir(vault_path, code)
    numbers = []
    names = []
    if directory.is_dir():
        for entry in directory.iterdir():
            if not entry.is_dir():
                continue
            names.append(entry.name)
            match = PARENT_RE.fullmatch(entry.name)
            if match is not None and match.group("category") == code:
                numbers.append(int(match.group("number")))
    _check_case_collision(names, f"category {code}")
    return _next_number(numbers, f"category {code}")


def next_run_number(vault_path, parent):
    numbers = [number for number, _ in _run_files(vault_path, parent)]
    directory = parent_dir(vault_path, parent)
    names = [e.name for e in directory.iterdir()] if directory.is_dir() else []
    _check_case_collision(names, parent)
    return _next_number(numbers, parent)


def _check_case_collision(names, subject):
    """vault-spec 7: names differing only in case collide on a case-insensitive
    filesystem, so refuse rather than pick one."""
    seen = {}
    for name in names:
        folded = name.lower()
        if folded in seen and seen[folded] != name:
            raise CardError(
                f"{subject} holds {seen[folded]!r} and {name!r}, which differ only in case; "
                "run 'hunt validate'",
                "LAYOUT-STEM-COLLISION",
            )
        seen[folded] = name


def _next_number(numbers, subject):
    """vault-spec 7: numbers present must be exactly 1..N. A gap means the tree
    already violates card-spec 7 invariant 2, so refuse rather than allocate
    into or past it."""
    present = sorted(set(numbers))
    if present and present != list(range(1, len(present) + 1)):
        missing = [n for n in range(1, present[-1]) if n not in set(present)]
        raise CardError(
            f"{subject} is missing number(s) {', '.join('%03d' % n for n in missing)}; "
            "refusing to allocate, run 'hunt validate'",
            "NUMBER-GAP",
        )
    number = len(present) + 1
    if number > MAX_NUMBER:
        raise CardError(f"{subject} already holds {MAX_NUMBER} cards", "NUMBER-OVERFLOW")
    return number


def _run_files(vault_path, parent):
    directory = parent_dir(vault_path, parent)
    found = []
    if directory.is_dir():
        for entry in directory.iterdir():
            if not entry.is_file() or not entry.name.endswith(".md"):
                continue
            match = RUN_RE.fullmatch(entry.name[:-3])
            if match is None or match.group("parent") != parent:
                continue
            number = int(match.group("number"))
            if number > 0:
                found.append((number, entry))
    found.sort()
    return found


def read_card(path):
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CardError(f"{path} is not valid UTF-8", "FILE-NON-ASCII") from exc


def write_card(path, text):
    """Write atomically: an interrupted write must not destroy the existing card."""
    target = Path(path)
    temporary = target.with_name(target.name + ".hunt-tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_parent(vault_path, parent):
    path = parent_path(vault_path, parent)
    if not path.is_file():
        raise CardError(f"{parent} has no index card", "LAYOUT-MISSING-INDEX")
    return path, parse_parent(read_card(path))


def load_runs(vault_path, parent):
    return [(path, parse_run(read_card(path))) for _, path in _run_files(vault_path, parent)]


def new_parent(parent, name, tags=(), why=""):
    ident = parse_parent_id(parent)
    _check_name(name)
    tags = list(tags)
    for tag in tags:
        if not is_valid_tag(tag):
            raise CardError(f"{tag!r} is not a valid tag", "FM-BAD-TAG")
    frontmatter = {
        "id": parent,
        "category": ident.category,
        "tags": tags,
        "status": STATUS_ACTIVE,
    }
    return Parent(frontmatter, name, why, "")


def new_run(run, run_date, previous_run=None, scope=None):
    ident = parse_run_id(run)
    if not is_valid_date(run_date):
        raise CardError(f"{run_date!r} is not a YYYY-MM-DD date", "FM-BAD-DATE")
    if scope is not None and not is_valid_scope(scope):
        raise CardError(f"{scope!r} is not a valid scope", "FM-BAD-SCOPE")
    frontmatter = {"id": run, "parent": ident.parent, "run_date": run_date}
    if ident.number == 1:
        if previous_run is not None:
            raise CardError("run 001 has no predecessor", "FM-FORBIDDEN-KEY")
    else:
        if previous_run is None:
            previous_run = run_id(ident.parent, ident.number - 1)
        parse_run_id(previous_run)
        frontmatter["previous_run"] = previous_run
    frontmatter["status"] = STATUS_OPEN
    if scope is not None:
        frontmatter["scope"] = scope
    return Run(frontmatter, "", "")


def _check_name(name):
    if not isinstance(name, str) or not name or name != name.strip():
        raise CardError("task name must be a non-empty trimmed line", "BODY-BAD-TASK-NAME")
    if any(character < " " or character > "~" for character in name):
        raise CardError("task name must be printable ASCII", "BODY-BAD-TASK-NAME")


class _FrontmatterLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader, node):
    loader.flatten_mapping(node)
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                "while constructing frontmatter",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        seen.add(key)
    return yaml.constructor.SafeConstructor.construct_mapping(loader, node, deep=True)


_FrontmatterLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def split_frontmatter(text):
    if not text.startswith(_FENCE):
        raise CardError("card does not open with a frontmatter fence", "FM-MISSING-FENCE")
    end = text.find("\n" + _FENCE, len(_FENCE) - 1)
    if end < 0:
        raise CardError("frontmatter fence is not closed", "FM-MISSING-FENCE")
    return text[len(_FENCE):end + 1], text[end + len(_FENCE) + 1:]


def frontmatter_key_order(text):
    block, _ = split_frontmatter(text)
    keys = []
    for line in block.split("\n"):
        match = _KEY_RE.match(line)
        if match is not None:
            keys.append(match.group(1))
    return keys


def _load_frontmatter(block):
    try:
        loaded = yaml.load(block, Loader=_FrontmatterLoader)
    except yaml.constructor.ConstructorError as exc:
        if "duplicate key" in str(exc):
            raise CardError(f"frontmatter has a {exc.problem}", "FM-DUPLICATE-KEY") from exc
        raise CardError(f"frontmatter is not valid YAML: {exc}", "FM-PARSE-ERROR") from exc
    except (yaml.YAMLError, TypeError, ValueError) as exc:
        raise CardError(f"frontmatter is not valid YAML: {exc}", "FM-PARSE-ERROR") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise CardError("frontmatter is not a mapping", "FM-PARSE-ERROR")
    return loaded


def parse_parent(text):
    block, body = split_frontmatter(text)
    frontmatter = _load_frontmatter(block)
    card = Parent(frontmatter)
    _fields(card, PARENT_REQUIRED_KEYS)
    ident = card.id
    if not is_valid_parent_id(ident):
        raise CardError(f"{ident!r} is not a parent ID", "FM-BAD-ID")
    lines = body.split("\n")
    start = _first_content(lines)
    prefix = f"# {ident} - "
    if start < 0 or not lines[start].startswith(prefix):
        raise CardError(f"H1 must begin {prefix!r}", "BODY-BAD-H1")
    name = lines[start][len(prefix):]
    _check_name(name)
    if sum(1 for line in lines if line.startswith("# ")) != 1:
        raise CardError("a parent card has exactly one H1", "BODY-BAD-H1")
    rest = lines[start + 1:]
    sections = _split_sections(rest)
    titles = [title for title, _, _ in sections]
    heads = [(title, level) for title, _, level in sections[:len(PARENT_SECTIONS)]]
    if heads != [(title, 2) for title in PARENT_SECTIONS]:
        missing = [title for title in PARENT_SECTIONS if title not in titles]
        if missing:
            raise CardError(
                f"parent card is missing section(s): {', '.join(missing)}",
                "BODY-MISSING-SECTION",
            )
        raise CardError(
            f"sections must be {', '.join(PARENT_SECTIONS)} in that order",
            "BODY-SECTION-ORDER",
        )
    why = _section_body(rest, sections, 0)
    extra = _sections_from(rest, sections, len(PARENT_SECTIONS))
    return Parent(frontmatter, name, why, extra)


def parse_run(text):
    block, body = split_frontmatter(text)
    frontmatter = _load_frontmatter(block)
    card = Run(frontmatter)
    _fields(card, RUN_REQUIRED_KEYS)
    card.scope  # optional, but a present value must still be well formed
    lines = body.split("\n")
    start = _first_content(lines)
    part_of = f"Part of: [[{card.parent}]]"
    if start < 0 or lines[start] != part_of:
        raise CardError(
            f"first non-empty line must be {part_of!r}", "BODY-MISSING-PART-OF"
        )
    start += 1
    previous = card.previous_run
    if previous is None:
        if start < len(lines) and lines[start].startswith("Previous:"):
            raise CardError(
                "a run without previous_run must carry no Previous line",
                "BODY-FORBIDDEN-PREVIOUS",
            )
    else:
        expected = f"Previous: [[{previous}]]"
        if start >= len(lines) or lines[start] != expected:
            raise CardError(
                f"the line after Part of must be {expected!r}", "BODY-MISSING-PREVIOUS"
            )
        start += 1
    rest = lines[start:]
    sections = _split_sections(rest)
    if not sections or sections[0][0] != OUTCOME or sections[0][2] != 2:
        raise CardError(f"run card is missing ## {OUTCOME}", "BODY-MISSING-OUTCOME")
    if sum(1 for title, _, level in sections if title == OUTCOME and level == 2) != 1:
        raise CardError(f"a run card has exactly one ## {OUTCOME}", "BODY-MISSING-OUTCOME")
    outcome = _section_body(rest, sections, 0)
    extra = _sections_from(rest, sections, 1)
    return Run(frontmatter, outcome, extra)


def _first_content(lines):
    for index, line in enumerate(lines):
        if line.strip():
            return index
    return -1


def _split_sections(lines):
    """Every ATX heading of level 2 or deeper starts a section (card-spec 3.1)."""
    sections = []
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match is not None:
            sections.append((match.group(2), index, len(match.group(1))))
    return sections


def _section_body(lines, sections, position):
    start = sections[position][1] + 1
    if position + 1 < len(sections):
        end = sections[position + 1][1]
    else:
        end = len(lines)
    return "\n".join(lines[start:end]).rstrip("\n")


def _sections_from(lines, sections, position):
    if position >= len(sections):
        return ""
    return "\n".join(lines[sections[position][1]:])


def render_parent(parent, runs):
    runs = list(runs)
    keys = [
        f"id: {parent.id}",
        f"category: {parent.category}",
        f"tags: [{', '.join(parent.tags)}]",
        f"status: {parent.status}",
    ]
    if runs:
        keys.append(f"latest_run: {runs[-1].id}")
        keys.append(f'latest_run_date: "{runs[-1].run_date}"')
    text = _frontmatter(keys)
    text += f"\n# {parent.id} - {parent.name}\n"
    text += "\n" + _section(WHY, parent.why)
    if runs:
        history = "\n".join(f"- [[{run.id}]] - {run.run_date}" for run in reversed(runs))
        text += "\n" + _section(LATEST_FINDINGS, f"![[{runs[-1].id}#{OUTCOME}]]")
        text += "\n" + _section(RUN_HISTORY, history)
    else:
        text += "\n" + _section(LATEST_FINDINGS, "")
        text += "\n" + _section(RUN_HISTORY, "")
    if parent.extra:
        text += "\n" + parent.extra
    return text


def render_run(run):
    keys = [
        f"id: {run.id}",
        f"parent: {run.parent}",
        f'run_date: "{run.run_date}"',
    ]
    previous = run.previous_run
    if previous is not None:
        keys.append(f"previous_run: {previous}")
    keys.append(f"status: {run.status}")
    scope = run.scope
    if scope is not None:
        keys.append(f'scope: "{scope}"')
    text = _frontmatter(keys)
    text += f"\nPart of: [[{run.parent}]]\n"
    if previous is not None:
        text += f"Previous: [[{previous}]]\n"
    text += "\n" + _section(OUTCOME, run.outcome)
    if run.extra:
        text += "\n" + run.extra
    return text


def _frontmatter(keys):
    return _FENCE + "".join(f"{key}\n" for key in keys) + _FENCE


def _section(title, body):
    if body:
        return f"## {title}\n{body}\n"
    return f"## {title}\n"
