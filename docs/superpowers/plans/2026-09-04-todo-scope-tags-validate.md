# TODO Batch: Category Tags, List Scope, Transition Validation - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear the three open `TODO.md` items: a parent card is created with its category as a default tag, a run card's `scope` becomes a list of one or more items assignable as `--scope windows,server`, and `hunt validate --against <rev>` implements card-spec 8.2 transition validation and replaces the placeholder step in the scaffolded workflow.

**Architecture:** Three independent changes to the existing layered CLI (`cli` -> `cards`/`validate`/`vault`), each test-first and each one commit. Task 1 touches only `cards.new_parent`. Task 2 widens the `scope` field in the model, renderer, validator and CLI while keeping the v5 scalar spelling readable and re-renderable byte for byte. Task 3 adds a new read-only function `validate.validate_transition(vault_path, revision)` that reads the accepted tree out of git via `vault.tracked_blobs` and compares it with the working tree, plus `vault.resolve_revision` and a `--against` option. Task 4 is documentation only.

**Tech Stack:** Python 3.11+, argparse (the repo has no Typer dependency: follow the existing argparse `type=` validator conventions), PyYAML, pytest, uv, the `git` binary via `subprocess`.

## Global Constraints

- Test first: in every task the failing test is written and *run* before the implementation.
- The test command is always `uv run pytest -q`, from the repo root.
- One commit per task, with the exact message given in the task.
- Baseline before any change: 250 passed.
- Never import a Python git library; all git access goes through `src/hunt/vault.py` helpers that shell out to `git`.
- The CLI is argparse, not Typer. New options are declared in `build_parser()` with a `type=` validator function that raises `argparse.ArgumentTypeError`.
- Source files are ASCII-only with LF endings; do not introduce non-ASCII characters (no smart quotes, no em dashes) into `src/`, `tests/`, `docs/` or the reference cards.
- Keep comments in the house style: explain why, not what.
- Cards in `docs/references/task-cards/` are fixtures for both the tests and the CI `reference-vault` job; when one is edited it must still validate clean.

### Decisions recorded (places the spec left a choice)

1. **The default tag is the category directory name** (`baseline`, `hunt`, `math`), not the code (`BSL`). card-spec 4 requires each tag to match `^[a-z0-9][a-z0-9_-]*$`, so an uppercase code cannot be a tag.
2. **No flag preserves the old behaviour.** card-spec places no constraint on tag *content*, so nothing in the spec demands an opt-out; `hunt new` grows no new option.
3. **`scope` items are rendered quoted**: `scope: ["windows", "server"]`. Unquoted flow scalars cannot hold `,`, `]` or a leading `#`, and v5 already quotes the value "so that a value YAML would otherwise coerce stays a string".
4. **A legacy scalar `scope: "windows"` is accepted on read and normalized to a one-item list** by `Run.scope`, and is **written back as a scalar** by `render_run`. Snapshot validation (card-spec 8.1) compares a card with its canonical re-render byte for byte, and invariant 9 forbids editing an accepted run; re-rendering old cards into the list spelling would make every v5 vault dirty and un-fixable. New cards always get the list spelling.
5. **8.2 is implemented as invariants 7-10 of Section 7**, which is exactly what 8.2 says ("additionally check invariants 7 through 10"). Findings use a new `transition.*` family: `transition.card-deleted`, `transition.number-reused`, `transition.field-changed`, `transition.status-reverted`, `transition.bad-status-transition`, `transition.retirement-freeze-broken`, `transition.outcome-changed`.
6. **A number is "reused" when the same card path holds a different task.** Two branches that both allocate `BSL-002` produce, after a merge or rebase, one `BSL-002` whose H1 name is not the accepted one; that is the cross-branch collision the TODO item describes, and it is what `transition.number-reused` reports.
7. **`--against` runs snapshot validation too**, then appends the transition findings; `--against` and `--id` are mutually exclusive.
8. **A card that does not parse is skipped by transition validation**, because snapshot validation already reports it and a second, worse-worded finding helps nobody.
9. **An added card is never a finding.** Invariants 7-10 constrain only what the accepted tree already contains.

---

### Task 1: Default category tag on a new parent card

**Files:**
- Modify: `/home/dotme/Code/hunt/src/hunt/cards.py`
- Test: `/home/dotme/Code/hunt/tests/test_cards.py`
- Test: `/home/dotme/Code/hunt/tests/test_cli.py` (one existing assertion)

**Interfaces:**
- Consumes: `cards.CATEGORIES` (`{"BSL": "baseline", "HNT": "hunt", "MTH": "math"}`), `cards.parse_parent_id(parent) -> ParentId(category, number)`.
- Produces: `cards.new_parent(parent, name, tags=(), why="", cadence=None) -> Parent` whose `frontmatter["tags"]` begins with the category directory name unless the caller already supplied it.

**Steps:**

- [ ] Append these tests to the end of `/home/dotme/Code/hunt/tests/test_cards.py`:

```python
# --- default category tag -----------------------------------------------------


def test_a_new_parent_is_tagged_with_its_category():
    """The category directory name is the tag: card-spec 4 requires a tag to
    match ^[a-z0-9][a-z0-9_-]*$, which the uppercase code cannot."""
    parent = cards.new_parent("HNT-001", "A hunt")
    assert parent.tags == ["hunt"]
    assert "tags: [hunt]\n" in cards.render_parent(parent, [])


def test_the_category_tag_is_added_for_every_category():
    assert cards.new_parent("BSL-001", "A baseline").tags == ["baseline"]
    assert cards.new_parent("HNT-001", "A hunt").tags == ["hunt"]
    assert cards.new_parent("MTH-001", "Some math").tags == ["math"]


def test_the_category_tag_comes_first_and_keeps_the_given_tags():
    parent = cards.new_parent("HNT-001", "A hunt", ["dns", "example"])
    assert parent.tags == ["hunt", "dns", "example"]


def test_the_category_tag_is_not_duplicated():
    parent = cards.new_parent("HNT-001", "A hunt", ["dns", "hunt"])
    assert parent.tags == ["dns", "hunt"]


def test_a_new_parent_card_round_trips_with_its_category_tag():
    parent = cards.new_parent("MTH-001", "Some math")
    text = cards.render_parent(parent, [])
    assert cards.parse_parent(text).tags == ["math"]
    assert cards.render_parent(cards.parse_parent(text), []) == text
```

- [ ] Run `uv run pytest -q tests/test_cards.py` and confirm the five new tests fail (`assert [] == ['hunt']` and similar). Do not continue if they pass.

- [ ] In `/home/dotme/Code/hunt/src/hunt/cards.py`, in `new_parent`, replace these three lines:

```python
    tags = list(tags)
    for tag in tags:
        if not is_valid_tag(tag):
            raise CardError(f"{tag!r} is not a valid tag", "FM-BAD-TAG")
```

with:

```python
    tags = list(tags)
    for tag in tags:
        if not is_valid_tag(tag):
            raise CardError(f"{tag!r} is not a valid tag", "FM-BAD-TAG")
    # Every task is at least its category, and the tag is the directory name:
    # card-spec 4 requires ^[a-z0-9][a-z0-9_-]*$, which the code (BSL) is not.
    category_tag = CATEGORIES[ident.category]
    if category_tag not in tags:
        tags.insert(0, category_tag)
```

- [ ] In `/home/dotme/Code/hunt/tests/test_cli.py`, at line 172, replace:

```python
    assert "tags: []" in front
```

with:

```python
    assert "tags: [hunt]" in front, "a new parent is tagged with its category"
```

- [ ] Run `uv run pytest -q` and confirm 255 passed.

- [ ] Commit:

```bash
git add src/hunt/cards.py tests/test_cards.py tests/test_cli.py
git commit -m "cards: tag a new parent with its category by default"
```

---

### Task 2: Run-card `scope` becomes a list

**Files:**
- Modify: `/home/dotme/Code/hunt/src/hunt/cards.py`
- Modify: `/home/dotme/Code/hunt/src/hunt/validate.py`
- Modify: `/home/dotme/Code/hunt/src/hunt/cli.py`
- Modify: `/home/dotme/Code/hunt/docs/references/task-cards/hunt/HNT-001/HNT-001.002.md`
- Test: `/home/dotme/Code/hunt/tests/test_cards.py`
- Test: `/home/dotme/Code/hunt/tests/test_validate.py`
- Test: `/home/dotme/Code/hunt/tests/test_cli.py`

**Interfaces:**
- Produces: `cards.is_valid_scope(value) -> bool` (one item, unchanged), `cards.is_valid_scope_list(values) -> bool` (a non-empty list of valid items).
- Produces: `Run.scope -> list[str] | None` (a legacy scalar reads back as a one-item list).
- Produces: `cards.new_run(run, run_date, previous_run=None, scope=None)` where `scope` is a list of items (a bare string is accepted as one item).
- Produces: `cli._scope("windows,server") -> ["windows", "server"]`, raising `ArgumentTypeError` otherwise.
- Renders: `scope: ["windows", "server"]` for a list, `scope: "windows"` for a card that already used the v5 scalar.

**Steps:**

- [ ] In `/home/dotme/Code/hunt/tests/test_cards.py`, replace the whole `# --- run scope ---` block (from the comment line down to and including `test_a_malformed_scope_in_an_existing_card_is_rejected_on_parse`) with:

```python
# --- run scope ---------------------------------------------------------------


def test_scope_is_optional_and_absent_by_default():
    """card-spec 6.1: an omitted scope leaves no key behind, so every card
    written before v5 still renders byte for byte."""
    run = cards.new_run("BSL-002.001", "2026-09-01")
    assert run.scope is None
    assert "scope" not in cards.render_run(run)


def test_scope_renders_last_as_a_list_and_round_trips():
    run = cards.new_run(
        "BSL-002.002", "2026-09-02", "BSL-002.001", ["windows", "servers"]
    )
    text = cards.render_run(run)
    keys = cards.frontmatter_key_order(text)
    assert keys == ["id", "parent", "run_date", "previous_run", "status", "scope"]
    assert 'scope: ["windows", "servers"]\n' in text
    assert cards.parse_run(text).scope == ["windows", "servers"]
    assert cards.render_run(cards.parse_run(text)) == text


def test_a_one_item_scope_is_still_written_as_a_list():
    run = cards.new_run("BSL-002.001", "2026-09-01", None, ["windows"])
    assert 'scope: ["windows"]\n' in cards.render_run(run)
    assert cards.parse_run(cards.render_run(run)).scope == ["windows"]


def test_a_bare_string_scope_is_taken_as_one_item():
    """A convenience for callers, not a second spelling: it is stored, and
    written, as a one-item list."""
    run = cards.new_run("BSL-002.001", "2026-09-01", None, "windows")
    assert run.scope == ["windows"]
    assert 'scope: ["windows"]\n' in cards.render_run(run)


def test_a_v5_scalar_scope_reads_as_a_one_item_list_and_renders_unchanged():
    """Invariant 9 forbids editing an accepted run, and 8.1 compares a card
    with its canonical re-render, so a v5 card must stay exactly itself."""
    text = (
        "---\n"
        "id: BSL-002.001\n"
        "parent: BSL-002\n"
        'run_date: "2026-09-01"\n'
        "status: open\n"
        'scope: "windows servers"\n'
        "---\n"
        "\n"
        "Part of: [[BSL-002]]\n"
        "\n"
        "## Outcome\n"
    )
    run = cards.parse_run(text)
    assert run.scope == ["windows servers"]
    assert cards.render_run(run) == text


@pytest.mark.parametrize(
    "scope",
    [
        ["windows"],
        ["windows", "servers"],
        ["clients", "on-prem", "firewalls"],
        ["EU tier-1 DMZ hosts (excluding lab)"],
        ["10.0.0.0/8"],
    ],
)
def test_scope_takes_any_well_formed_value(scope):
    """The value set is deliberately open: the tool checks shape, never meaning."""
    run = cards.new_run("BSL-002.001", "2026-09-01", None, scope)
    assert cards.parse_run(cards.render_run(run)).scope == scope


@pytest.mark.parametrize(
    "scope",
    [
        [],
        [""],
        [" "],
        ["windows ", "servers"],
        [" windows"],
        ['say "windows"'],
        ["back\\slash"],
        ["two\nlines"],
        [7],
        "",
        7,
        {"windows": True},
    ],
)
def test_scope_rejects_a_malformed_value(scope):
    with pytest.raises(CardError):
        cards.new_run("BSL-002.001", "2026-09-01", None, scope)


def test_a_malformed_scope_in_an_existing_card_is_rejected_on_parse():
    text = cards.render_run(
        cards.new_run("BSL-002.001", "2026-09-01", None, ["windows"])
    )
    with pytest.raises(CardError):
        cards.parse_run(text.replace('scope: ["windows"]', "scope: 7"))
    with pytest.raises(CardError):
        cards.parse_run(text.replace('scope: ["windows"]', "scope: []"))
```

- [ ] Run `uv run pytest -q tests/test_cards.py` and confirm the new scope tests fail. Do not continue if they pass.

- [ ] In `/home/dotme/Code/hunt/src/hunt/cards.py`, replace the `Run.scope` property:

```python
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
```

with:

```python
    @property
    def scope(self):
        """card-spec 6.1: one or more free-text items. A v5 scalar is read as a
        one-item list; render_run writes back whichever spelling the file used,
        so a run accepted under v5 stays byte for byte itself (invariant 9)."""
        if "scope" not in self.frontmatter:
            return None
        value = self.frontmatter["scope"]
        items = [value] if isinstance(value, str) else value
        if not isinstance(items, list) or not all(
            isinstance(item, str) for item in items
        ):
            raise CardError(
                "scope must be a list of strings, or a string", "FM-BAD-TYPE"
            )
        if not is_valid_scope_list(items):
            raise CardError(f"{value!r} is not a valid scope", "FM-BAD-SCOPE")
        return list(items)
```

- [ ] In `/home/dotme/Code/hunt/src/hunt/cards.py`, immediately after the existing `is_valid_scope` function:

```python
def is_valid_scope(value):
    if not isinstance(value, str) or value != value.strip():
        return False
    return SCOPE_RE.fullmatch(value) is not None
```

add:

```python
def is_valid_scope_list(values):
    """card-spec 6.1: one or more items, each well formed. An empty list is not
    an "unset scope"; the way to record no scope is to omit the key."""
    if not isinstance(values, list) or not values:
        return False
    return all(is_valid_scope(item) for item in values)
```

- [ ] In `/home/dotme/Code/hunt/src/hunt/cards.py`, in `new_run`, replace:

```python
    if scope is not None and not is_valid_scope(scope):
        raise CardError(f"{scope!r} is not a valid scope", "FM-BAD-SCOPE")
```

with:

```python
    if scope is not None:
        # A bare string is a convenience for one item, not a second spelling:
        # what is stored, and written, is always a list.
        scope = [scope] if isinstance(scope, str) else scope
        if not is_valid_scope_list(scope):
            raise CardError(f"{scope!r} is not a valid scope", "FM-BAD-SCOPE")
        scope = list(scope)
```

- [ ] In `/home/dotme/Code/hunt/src/hunt/cards.py`, in `render_run`, replace:

```python
    scope = run.scope
    if scope is not None:
        keys.append(f'scope: "{scope}"')
```

with:

```python
    run.scope  # a present value must be well formed before it is written back
    scope = run.frontmatter.get("scope")
    if scope is not None:
        if isinstance(scope, str):
            # A v5 card is written back as it was found: an accepted run's
            # fields must not change (card-spec 7, invariant 9).
            keys.append(f'scope: "{scope}"')
        else:
            items = ", ".join(f'"{item}"' for item in scope)
            keys.append(f"scope: [{items}]")
```

- [ ] Run `uv run pytest -q tests/test_cards.py` and confirm the scope tests pass.

- [ ] In `/home/dotme/Code/hunt/tests/test_validate.py`, replace the whole `# --- run scope ---` block (from the comment line down to and including `test_scope_on_a_parent_card_is_an_unknown_key`) with:

```python
# --- run scope ---------------------------------------------------------------


HNT_RUN2 = "hunt/HNT-001/HNT-001.002.md"
SCOPE = 'scope: ["windows", "workstations"]'


def test_scope_is_optional(good):
    """card-spec 6.1: dropping the key is not a finding; the reference vault
    validates clean both with the field and without it."""
    edit(good, HNT_RUN2, "\n" + SCOPE, "")
    assert validate_vault(good.path) == []


def test_scope_value_is_never_checked_against_a_list(good):
    """No vocabulary exists; an unusual value is as valid as a familiar one."""
    edit(good, HNT_RUN2, SCOPE, 'scope: ["three lab racks", "a coffee machine"]')
    assert validate_vault(good.path) == []


def test_a_one_item_scope_validates(good):
    edit(good, HNT_RUN2, SCOPE, 'scope: ["windows"]')
    assert validate_vault(good.path) == []


def test_a_v5_scalar_scope_still_validates(good):
    """Schema v5 wrote one quoted string. Invariant 9 forbids editing an
    accepted run, so such a card must stay valid and must re-render unchanged."""
    edit(good, HNT_RUN2, SCOPE, 'scope: "windows workstations"')
    assert validate_vault(good.path) == []


@pytest.mark.parametrize(
    "value",
    [
        "[]",
        '[""]',
        '[" windows"]',
        '["windows "]',
        '["back\\\\slash"]',
        '["windows", 7]',
        '""',
        "7",
        "{a: b}",
    ],
)
def test_malformed_scope_is_reported(good, value):
    edit(good, HNT_RUN2, SCOPE, "scope: " + value)
    assert set(codes(good.path)) & {"frontmatter.bad-scope", "frontmatter.bad-type"}


def test_scope_before_status_is_a_key_order_finding(good):
    edit(
        good,
        HNT_RUN2,
        "status: complete\n" + SCOPE + "\n",
        SCOPE + "\nstatus: complete\n",
    )
    assert "frontmatter.key-order" in codes(good.path)


def test_scope_on_a_parent_card_is_an_unknown_key(good):
    """scope is a run field; the parent schema stays closed against it."""
    edit(good, BSL, "status: active\n", 'status: active\nscope: ["windows"]\n')
    assert "frontmatter.unknown-key" in codes(good.path)
```

- [ ] In `/home/dotme/Code/hunt/docs/references/task-cards/hunt/HNT-001/HNT-001.002.md`, replace the line:

```yaml
scope: "windows workstations"
```

with:

```yaml
scope: ["windows", "workstations"]
```

- [ ] Run `uv run pytest -q tests/test_validate.py` and confirm the malformed-scope cases `[]`, `[""]`, `[" windows"]`, `["windows "]`, `["back\\slash"]`, `["windows", 7]` and `{a: b}` fail (the validator still demands a string). Do not continue if they pass.

- [ ] In `/home/dotme/Code/hunt/src/hunt/validate.py`, replace `_check_scope` in full:

```python
def _check_scope(path, data, findings):
    """card-spec 6.1: scope is free text, so only its shape is checked here.
    No value set exists, and inventing one in the validator would be exactly
    the enforcement the spec withholds."""
    value = data["scope"]
    if not isinstance(value, str):
        findings.append(
            Finding(path, "frontmatter.bad-type", "scope must be a quoted string")
        )
        return
    if not cards.is_valid_scope(value):
        findings.append(
            Finding(
                path,
                "frontmatter.bad-scope",
                f"scope {_show(value)} must be a single non-empty line of printable "
                "ASCII, without a double quote, a backslash, or surrounding spaces",
            )
        )
```

with:

```python
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
```

Note: the exact wording of the second message above must match the wording used in the `cli._scope` error text below only in spirit, not in bytes; do not try to share the string.

- [ ] Run `uv run pytest -q tests/test_validate.py` and confirm it passes.

- [ ] In `/home/dotme/Code/hunt/tests/test_cli.py`, replace the whole `# --- run scope ---` block (from the comment line down to and including `test_run_rejects_a_malformed_scope`) with:

```python
# --- run scope ---------------------------------------------------------------


def test_run_records_a_scope_when_given(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h", "--name", NAME).returncode == 0
    result = hunt(
        vault, "run", "--id", "HNT-001", "--date", DATE1, "--scope", "windows,servers"
    )
    assert result.returncode == 0, result.stderr

    front, _ = split_card(card(vault, "HNT-001.001.md").read_text())
    assert front[-1] == 'scope: ["windows", "servers"]', "scope is the last key"
    assert hunt(vault, "validate").returncode == 0
    assert_clean(vault)


def test_run_records_a_one_item_scope(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h", "--name", NAME).returncode == 0
    result = hunt(
        vault, "run", "--id", "HNT-001", "--date", DATE1, "--scope", "windows"
    )
    assert result.returncode == 0, result.stderr

    front, _ = split_card(card(vault, "HNT-001.001.md").read_text())
    assert front[-1] == 'scope: ["windows"]'
    assert hunt(vault, "validate").returncode == 0


def test_run_omits_scope_when_not_given(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h", "--name", NAME).returncode == 0
    assert hunt(vault, "run", "--id", "HNT-001", "--date", DATE1).returncode == 0

    front, _ = split_card(card(vault, "HNT-001.001.md").read_text())
    assert not [line for line in front if line.startswith("scope")]
    assert hunt(vault, "validate").returncode == 0


@pytest.mark.parametrize(
    "scope",
    [
        "",
        ",",
        "windows,",
        ",windows",
        "windows,,servers",
        "windows, servers",
        " windows",
        'say "windows"',
        "back\\slash",
    ],
)
def test_run_rejects_a_malformed_scope(vault, scope):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h", "--name", NAME).returncode == 0
    result = hunt(vault, "run", "--id", "HNT-001", "--date", DATE1, "--scope", scope)
    assert result.returncode == 2
    assert "invalid scope" in result.stderr
    assert not card(vault, "HNT-001.001.md").exists()
```

- [ ] Run `uv run pytest -q tests/test_cli.py` and confirm the new scope tests fail (`--scope windows,servers` is still written as one string). Do not continue if they pass.

- [ ] In `/home/dotme/Code/hunt/src/hunt/cli.py`, replace `_scope` in full:

```python
def _scope(value):
    if not cards.is_valid_scope(value):
        raise argparse.ArgumentTypeError(
            "invalid scope %r (expected a single non-empty line of printable ASCII, "
            "without a double quote, a backslash, or surrounding spaces)" % value
        )
    return value
```

with:

```python
def _scope(value):
    """--scope windows,servers -> ["windows", "servers"] (card-spec 6.1). The
    separator is a bare comma: an item may hold spaces, so splitting on ", "
    would make "windows, servers" mean two different things by one keystroke."""
    items = value.split(",")
    if not all(cards.is_valid_scope(item) for item in items):
        raise argparse.ArgumentTypeError(
            "invalid scope %r (expected one or more items separated by a comma with "
            "no space, each a single non-empty line of printable ASCII, without a "
            "double quote, a backslash, or surrounding spaces)" % value
        )
    return items
```

- [ ] In `/home/dotme/Code/hunt/src/hunt/cli.py`, in `build_parser()`, replace the `--scope` help line:

```python
        help="free-text scope of the run, e.g. 'windows servers'; omitted if unset",
```

with:

```python
        help="comma-separated free-text scope, e.g. windows,servers; omitted if unset",
```

and replace its `metavar="<scope>"` with `metavar="<scope>[,<scope>...]"`.

- [ ] Run `uv run pytest -q` and confirm 261 passed.

- [ ] Commit:

```bash
git add src/hunt/cards.py src/hunt/validate.py src/hunt/cli.py \
  docs/references/task-cards/hunt/HNT-001/HNT-001.002.md \
  tests/test_cards.py tests/test_validate.py tests/test_cli.py
git commit -m "cards: make run scope a list of one or more items"
```

---

### Task 3: `hunt validate --against <rev>` (card-spec 8.2)

**Files:**
- Modify: `/home/dotme/Code/hunt/src/hunt/vault.py`
- Modify: `/home/dotme/Code/hunt/src/hunt/validate.py`
- Modify: `/home/dotme/Code/hunt/src/hunt/cli.py`
- Modify: `/home/dotme/Code/hunt/src/hunt/scaffold.py`
- Modify: `/home/dotme/Code/hunt/.github/workflows/ci.yml`
- Create: `/home/dotme/Code/hunt/tests/test_transition.py`

**Interfaces:**
- Consumes: `vault.tracked_blobs(vault, revision) -> list[tuple[str, bytes]]`, `cards.parse_parent(text)`, `cards.parse_run(text)`, `cards.read_card(path)`, `cards.DIRECTORIES`, `cards.RUN_STATUSES`, `cards.STATUS_ACTIVE`, `cards.STATUS_RETIRED`, `validate.Finding(path, code, message)`.
- Produces: `vault.resolve_revision(vault, revision) -> str` (a commit sha, or raises `VaultError`).
- Produces: `validate.validate_transition(vault_path, revision) -> list[Finding]`.
- Produces: `hunt validate --against <rev>`, exit 0 when clean, 1 on any finding or on an unknown revision.

**Steps:**

- [ ] Create `/home/dotme/Code/hunt/tests/test_transition.py` with exactly this content:

```python
import shutil
from pathlib import Path

import pytest

from hunt.validate import validate_transition

REFERENCES = Path(__file__).resolve().parents[1] / "docs" / "references" / "task-cards"

BSL = "baseline/BSL-001/BSL-001.md"
BSL_RUN2 = "baseline/BSL-001/BSL-001.002.md"
HNT = "hunt/HNT-001/HNT-001.md"


@pytest.fixture
def accepted(vault):
    """The reference vault, committed. That commit is the accepted tree; the
    working tree on top of it is the proposed one (card-spec 8.2)."""
    for entry in REFERENCES.iterdir():
        shutil.copytree(entry, vault.path / entry.name)
    vault.git("add", "-A")
    vault.git("commit", "-q", "-m", "accepted")
    return vault


def codes(vault, revision="HEAD"):
    return sorted(finding.code for finding in validate_transition(vault.path, revision))


def edit(vault, relative, old, new):
    path = vault.path / relative
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {relative}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


def test_an_unchanged_tree_is_clean(accepted):
    assert validate_transition(accepted.path, "HEAD") == []


def test_adding_a_card_is_not_a_finding(accepted):
    """Invariants 7-10 constrain what the accepted tree already holds; a new
    parent, and a new run under an existing one, are the normal case."""
    (accepted.path / "hunt/HNT-002").mkdir()
    (accepted.path / "hunt/HNT-002/HNT-002.md").write_text(
        "---\nid: HNT-002\ncategory: HNT\ntags: [hunt]\nstatus: active\n---\n\n"
        "# HNT-002 - A second hunt\n\n## Why\n\n## Latest findings\n\n"
        "## Run history\n",
        encoding="utf-8",
    )
    assert validate_transition(accepted.path, "HEAD") == []


def test_deleting_an_accepted_card_is_reported(accepted):
    (accepted.path / BSL_RUN2).unlink()
    assert codes(accepted) == ["transition.card-deleted"]


def test_renaming_a_card_is_a_deletion_of_the_old_name(accepted):
    (accepted.path / BSL_RUN2).rename(accepted.path / "baseline/BSL-001/BSL-001.009.md")
    assert "transition.card-deleted" in codes(accepted)


def test_a_number_holding_a_different_task_is_reported(accepted):
    """Two branches that each allocated BSL-001 leave one BSL-001 whose H1 is
    not the accepted one. That is the cross-branch collision (invariant 7)."""
    edit(
        accepted,
        BSL,
        "# BSL-001 - Monthly DNS query volume baseline",
        "# BSL-001 - Something else entirely",
    )
    assert "transition.number-reused" in codes(accepted)


def test_changing_a_run_field_is_reported(accepted):
    edit(accepted, BSL_RUN2, 'run_date: "2026-08-31"', 'run_date: "2026-08-30"')
    assert "transition.field-changed" in codes(accepted)


def test_changing_a_run_scope_is_reported(accepted):
    edit(
        accepted,
        "hunt/HNT-001/HNT-001.002.md",
        'scope: ["windows", "workstations"]',
        'scope: ["linux"]',
    )
    assert "transition.field-changed" in codes(accepted)


def test_a_run_status_may_advance_one_step(accepted):
    edit(accepted, BSL_RUN2, "status: complete", "status: void")
    assert validate_transition(accepted.path, "HEAD") == []


def test_a_run_status_may_not_go_backwards(accepted):
    edit(accepted, BSL_RUN2, "status: complete", "status: open")
    assert "transition.bad-status-transition" in codes(accepted)


def test_an_accepted_outcome_may_be_appended_to(accepted):
    edit(accepted, BSL_RUN2, "## Outcome\n", "## Outcome\n")
    path = accepted.path / BSL_RUN2
    path.write_text(path.read_text(encoding="utf-8") + "One more line.\n", encoding="utf-8")
    assert validate_transition(accepted.path, "HEAD") == []


def test_rewriting_an_accepted_outcome_is_reported(accepted):
    path = accepted.path / BSL_RUN2
    text = path.read_text(encoding="utf-8")
    head, _, _ = text.partition("## Outcome\n")
    path.write_text(head + "## Outcome\nA different story.\n", encoding="utf-8")
    assert "transition.outcome-changed" in codes(accepted)


def test_changing_parent_tags_is_reported(accepted):
    edit(accepted, BSL, "tags: [dns, baseline, example]", "tags: [dns]")
    assert "transition.field-changed" in codes(accepted)


def test_a_parent_may_be_retired_and_may_change_cadence(accepted):
    edit(accepted, BSL, "status: active", "status: retired")
    assert validate_transition(accepted.path, "HEAD") == []


def test_retirement_never_reverts(accepted):
    edit(accepted, BSL, "status: active", "status: retired")
    accepted.git("add", "-A")
    accepted.git("commit", "-q", "-m", "retired")
    edit(accepted, BSL, "status: retired", "status: active")
    assert "transition.status-reverted" in codes(accepted)


def test_latest_run_may_not_move_backwards(accepted):
    edit(accepted, BSL, "latest_run: BSL-001.002", "latest_run: BSL-001.001")
    assert "transition.field-changed" in codes(accepted)


def test_a_card_that_does_not_parse_is_left_to_snapshot_validation(accepted):
    """A broken card is already a snapshot finding; repeating it here in worse
    words helps nobody."""
    (accepted.path / BSL_RUN2).write_text("not a card\n", encoding="utf-8")
    assert validate_transition(accepted.path, "HEAD") == []


def test_an_empty_revision_reports_nothing(accepted):
    """The root commit holds only .gitattributes: nothing was accepted yet."""
    root = accepted.git("rev-list", "--max-parents=0", "HEAD").strip()
    assert validate_transition(accepted.path, root) == []
```

- [ ] Run `uv run pytest -q tests/test_transition.py` and confirm every test fails with `ImportError: cannot import name 'validate_transition'`. Do not continue if any pass.

- [ ] In `/home/dotme/Code/hunt/src/hunt/vault.py`, add this function immediately before `def tracked_blobs`:

```python
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
```

- [ ] In `/home/dotme/Code/hunt/src/hunt/validate.py`, append this block to the end of the file:

```python
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
            else:
                before = cards.parse_run(accepted[name])
                after = cards.parse_run(proposed[name])
        except cards.CardError:
            # A card that does not parse is already a snapshot finding.
            continue
        if is_index:
            _check_parent_transition(path, revision, before, after, findings)
        else:
            _check_run_transition(path, revision, before, after, findings)
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


def _check_parent_transition(path, revision, before, after, findings):
    """card-spec 7, invariants 7, 9 and 10 for one parent index card."""
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


def _check_run_transition(path, revision, before, after, findings):
    """card-spec 7, invariant 9 for one run card: only status advances, and the
    Outcome may only be appended to."""
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


def _run_number(value):
    """The run number in an id, or 0 when it is not a run id at all (which is a
    snapshot finding, not this function's business)."""
    try:
        return cards.parse_run_id(value).number
    except cards.CardError:
        return 0
```

- [ ] Check that `validate.py` already imports what the new code needs: `from pathlib import Path`, `from . import cards`, `from . import vault as vaultmod` (the module's existing import spelling for vault; if it differs, use the name already imported at the top of the file). Add nothing that is already there.

- [ ] Run `uv run pytest -q tests/test_transition.py` and confirm all 17 tests pass.

- [ ] In `/home/dotme/Code/hunt/src/hunt/cli.py`, change the validate import line:

```python
from .validate import validate_parent_dir, validate_vault
```

to:

```python
from .validate import validate_parent_dir, validate_transition, validate_vault
```

- [ ] In `/home/dotme/Code/hunt/src/hunt/cli.py`, in `cmd_validate`, replace:

```python
    if args.id is None:
        findings = validate_vault(config.vault_path)
```

with:

```python
    if args.against is not None:
        # Resolve first so a typo is an error, not an all-clear against a tree
        # git never found. The user's spelling is what the findings quote.
        vault.resolve_revision(config.vault_path, args.against)
        findings = validate_vault(config.vault_path) + validate_transition(
            config.vault_path, args.against
        )
    elif args.id is None:
        findings = validate_vault(config.vault_path)
```

- [ ] In `/home/dotme/Code/hunt/src/hunt/cli.py`, in `build_parser()`, replace:

```python
    validate = subparsers.add_parser("validate", help="validate the vault")
    validate.add_argument(
        "--id", type=_card_id, metavar="<ID>", help="restrict findings to one card"
    )
    validate.set_defaults(func=cmd_validate)
```

with:

```python
    validate = subparsers.add_parser("validate", help="validate the vault")
    # Mutually exclusive: --id narrows to one card, --against widens to a whole
    # tree comparison. Asking for both is a mistake worth reporting.
    scope_of_run = validate.add_mutually_exclusive_group()
    scope_of_run.add_argument(
        "--id", type=_card_id, metavar="<ID>", help="restrict findings to one card"
    )
    scope_of_run.add_argument(
        "--against",
        metavar="<rev>",
        help="also check the transition from a git revision, e.g. origin/main "
        "(card-spec 8.2)",
    )
    validate.set_defaults(func=cmd_validate)
```

- [ ] Append these tests to the end of `/home/dotme/Code/hunt/tests/test_cli.py`:

```python
# --- transition validation ----------------------------------------------------


def test_validate_against_head_is_clean_for_an_untouched_vault(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h", "--name", NAME).returncode == 0
    assert hunt(vault, "run", "--id", "HNT-001", "--date", DATE1).returncode == 0

    result = hunt(vault, "validate", "--against", "HEAD")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""


def test_validate_against_head_rejects_a_deleted_card(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h", "--name", NAME).returncode == 0
    assert hunt(vault, "run", "--id", "HNT-001", "--date", DATE1).returncode == 0
    card(vault, "HNT-001.001.md").unlink()

    result = hunt(vault, "validate", "--against", "HEAD")
    assert result.returncode == 1
    assert "transition.card-deleted" in result.stdout


def test_validate_against_head_rejects_a_reused_number(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h", "--name", NAME).returncode == 0
    path = card(vault, "HNT-001.md")
    path.write_text(
        path.read_text().replace(f"# HNT-001 - {NAME}", "# HNT-001 - Another task"),
        encoding="utf-8",
    )

    result = hunt(vault, "validate", "--against", "HEAD")
    assert result.returncode == 1
    assert "transition.number-reused" in result.stdout


def test_validate_against_an_unknown_revision_says_so(vault):
    assert hunt(vault, "init").returncode == 0
    result = hunt(vault, "validate", "--against", "no-such-branch")
    assert result.returncode == 1
    assert "unknown revision: no-such-branch" in result.stderr


def test_validate_refuses_id_and_against_together(vault):
    assert hunt(vault, "init").returncode == 0
    result = hunt(vault, "validate", "--id", "HNT-001", "--against", "HEAD")
    assert result.returncode == 2
    assert "not allowed with" in result.stderr
```

- [ ] Run `uv run pytest -q` and confirm 283 passed.

- [ ] In `/home/dotme/Code/hunt/src/hunt/scaffold.py`, inside the `WORKFLOW` string, replace:

```yaml
      - name: transition validation against main (card-spec 8.2)
        # Not enforced yet: `hunt validate --against <rev>` does not exist.
        # When it does, replace the echo with:
        #   uvx --from "git+https://github.com/dotknewt/hunt@$HUNT_REF" \\
        #     hunt validate --against origin/main
        if: github.event_name == 'pull_request'
        run: echo "transition validation (card-spec 8.2) is not implemented yet"
```

with:

```yaml
      - name: transition validation against main (card-spec 8.2)
        if: github.event_name == 'pull_request'
        run: |
          git fetch --no-tags --quiet origin main
          uvx --from "git+https://github.com/dotknewt/hunt@$HUNT_REF" \\
            hunt validate --against origin/main
```

Keep the doubled backslash: the surrounding `WORKFLOW` is a normal Python string, and the existing lines around it use `\\` for a shell line continuation.

- [ ] In `/home/dotme/Code/hunt/.github/workflows/ci.yml`, in the `reference-vault` job, immediately after the step that runs `uv run hunt validate`, add:

```yaml
      - name: transition validation finds nothing against an unchanged tree
        run: uv run hunt validate --against main
```

- [ ] Run `uv run pytest -q` again and confirm 283 passed (the scaffold tests assert the file set and its bytes are ASCII/LF, not the step text).

- [ ] Commit:

```bash
git add src/hunt/vault.py src/hunt/validate.py src/hunt/cli.py \
  src/hunt/scaffold.py .github/workflows/ci.yml \
  tests/test_transition.py tests/test_cli.py
git commit -m "validate: implement --against for card-spec 8.2 transition checks"
```

---

### Task 4: Documentation and TODO

**Files:**
- Modify: `/home/dotme/Code/hunt/TODO.md`
- Modify: `/home/dotme/Code/hunt/docs/card-spec.md`
- Modify: `/home/dotme/Code/hunt/docs/vault-spec.md`
- Modify: `/home/dotme/Code/hunt/docs/CODEBASE.md`
- Modify: `/home/dotme/Code/hunt/README.md`

**Interfaces:**
- Consumes: the behaviour built in Tasks 1-3. No code changes in this task.
- Produces: card-spec v7 (scope is a list), and docs that no longer describe transition validation as unimplemented.

**Steps:**

- [ ] Replace the whole content of `/home/dotme/Code/hunt/TODO.md` with:

```markdown
# TODO
*tasks by priority*

# Future
- Make task and/or run card generation possible using the obsidian app?
```

- [ ] In `/home/dotme/Code/hunt/docs/card-spec.md`, change the version line:

```markdown
**Version:** 6
```

to:

```markdown
**Version:** 7
```

- [ ] In `/home/dotme/Code/hunt/docs/card-spec.md`, insert a new changelog paragraph immediately after the line `**Changelog:**` starts, i.e. replace:

```markdown
**Changelog:** v6 adds the optional parent-card field `cadence` (Sections 4
```

with:

```markdown
**Changelog:** v7 widens the optional run-card field `scope` (Sections 4 and
6.1) from a single quoted string to a flow sequence of one or more quoted
strings, written `scope: ["windows", "servers"]`. Each item obeys the shape v5
gave the scalar; the sequence MUST NOT be empty, and the way to record no scope
is still to omit the key. A card written against v5 carrying a bare quoted
string remains valid and MUST be read as a one-item sequence and re-rendered
in the spelling it uses: invariant 9 of Section 7 forbids editing an accepted
run, so a v5 card can never be migrated in place.
v6 adds the optional parent-card field `cadence` (Sections 4
```

- [ ] In `/home/dotme/Code/hunt/docs/card-spec.md`, replace the Section 4 `scope` table row:

```markdown
| `scope` | quoted string | a single non-empty line; printable ASCII per Section 3.1; no leading or trailing space; MUST NOT contain `"` or `\`; quoted so that a value YAML would otherwise coerce stays a string. **No value set is defined and none MUST be enforced** |
```

with:

```markdown
| `scope` | array of quoted strings | one or more items, written as a single-line flow sequence with items separated by `, `; MUST NOT be empty (`[]`); each item is a single non-empty line, printable ASCII per Section 3.1, no leading or trailing space, MUST NOT contain `"` or `\`, and is quoted so that a value YAML would otherwise coerce stays a string. A bare quoted string (the v5 spelling) MUST be accepted, read as a one-item sequence, and re-rendered as it was found. **No value set is defined and none MUST be enforced** |
```

- [ ] In `/home/dotme/Code/hunt/docs/card-spec.md`, in the Section 6.1 example, replace:

```yaml
scope: "windows servers"    # OPTIONAL
```

with:

```yaml
scope: ["windows", "servers"]   # OPTIONAL
```

- [ ] In `/home/dotme/Code/hunt/docs/card-spec.md`, replace this paragraph of Section 6.1:

```markdown
**`scope` is free text, and its values are not a closed set.** It records what
this run covered - `"windows"`, `"servers"`, `"clients"`, `"on-prem"`,
`"firewalls"`, or any phrase the hunter finds useful. A validator MUST check
the *shape* given in Section 4 and MUST NOT check the value against any list,
vocabulary, or registry: no such list exists, and this document defines none.
```

with:

```markdown
**`scope` is free text, and its values are not a closed set.** It records what
this run covered - `["windows"]`, `["windows", "servers"]`, `["on-prem"]`, or
any phrase the hunter finds useful, one item or several. A validator MUST check
the *shape* given in Section 4 and MUST NOT check any item against a list,
vocabulary, or registry: no such list exists, and this document defines none.
The order of items carries no meaning, and no rule elsewhere derives from it.
```

- [ ] In `/home/dotme/Code/hunt/docs/vault-spec.md`, replace:

```markdown
  SHOULD run transition validation (`docs/card-spec.md` Section 8.2) against
  `main` once a validator implements it; until one does, that step is a
  placeholder and the check is a duty of the human review (Section 4). The
```

with:

```markdown
  SHOULD run transition validation (`docs/card-spec.md` Section 8.2) against
  `main`, which `hunt validate --against origin/main` performs, and fail on any
  finding. The
```

- [ ] In `/home/dotme/Code/hunt/README.md`, replace:

```markdown
hunt run --id HNT-001 --scope "windows servers"
```

with:

```markdown
hunt run --id HNT-001 --scope windows,servers
```

- [ ] In `/home/dotme/Code/hunt/README.md`, replace:

```markdown
`hunt run --scope` records what the run covered - `windows`, `on-prem`,
`clients`, or any phrase that fits. It is optional and free text: `hunt` checks
that the value is a single line of printable ASCII and nothing more. There is
no list of permitted scopes, and nothing enforces one.
```

with:

```markdown
`hunt run --scope` records what the run covered - `windows`, `on-prem`,
`clients`, or any phrase that fits. Give one item or several, separated by a
comma with no space (`--scope windows,servers`); they are stored as a list. It
is optional and free text: `hunt` checks that each item is a single line of
printable ASCII and nothing more. There is no list of permitted scopes, and
nothing enforces one.

`hunt new` tags a new parent card with its own category (`baseline`, `hunt` or
`math`) so that every card is findable by the thing it always is. Any tag
already present is kept, and the category tag is never added twice.
```

- [ ] In `/home/dotme/Code/hunt/README.md`, replace:

```markdown
Transition validation (`docs/card-spec.md` Section 8.2: nothing accepted is
deleted, renumbered or reused across branches) is not implemented yet. The
workflow carries a placeholder step for it, and until `hunt validate --against`
exists the check is part of the human review of each merge.
```

with:

```markdown
Transition validation (`docs/card-spec.md` Section 8.2: nothing accepted is
deleted, renumbered or reused across branches) runs as `hunt validate --against
origin/main`, which the scaffolded workflow invokes on every pull request. It
reads the accepted tree out of git and reports a `transition.*` finding for a
deleted card, a number now holding a different task, an edited field of an
accepted card, a status that went backwards, or a rewritten Outcome. It exits
non-zero on any finding, and on a revision git cannot resolve.
```

- [ ] In `/home/dotme/Code/hunt/docs/CODEBASE.md`, replace:

```markdown
- `_check_frontmatter`, `_check_keys` (duplicates, forbidden, unknown, missing,
  order), `_check_values`, `_check_category`, `_check_tags`, `_check_scope`.
```

with:

```markdown
- `_check_frontmatter`, `_check_keys` (duplicates, forbidden, unknown, missing,
  order), `_check_values`, `_check_category`, `_check_tags`, `_check_scope`
  (a list of items, or a v5 scalar read as one item).
- `validate_transition(vault_path, revision)`: card-spec 8.2, invariants 7-10
  between the working tree and the tree recorded at `revision`. Helpers
  `_revision_cards`, `_tree_cards`, `_is_card_name`,
  `_check_parent_transition`, `_check_run_transition`, `_run_number`. Finding
  family `transition.*`: `card-deleted`, `number-reused`, `field-changed`,
  `status-reverted`, `bad-status-transition`, `retirement-freeze-broken`,
  `outcome-changed`.
```

- [ ] In `/home/dotme/Code/hunt/docs/CODEBASE.md`, replace:

```markdown
  (`.github/workflows/hunt.yml`: a `validate` job running `hunt validate` and a
  `line-endings` job; the merge-time transition check is a placeholder step),
```

with:

```markdown
  (`.github/workflows/hunt.yml`: a `validate` job running `hunt validate` and,
  on a pull request, `hunt validate --against origin/main`, plus a
  `line-endings` job),
```

- [ ] In `/home/dotme/Code/hunt/docs/CODEBASE.md`, replace:

```markdown
2. **Transition validation is unimplemented.** card-spec 8.2 (`hunt validate
   --against <rev>`) is tracked in `TODO.md`; the scaffolded workflow carries an
   echo placeholder step. Cross-branch numbering conflicts are therefore only
   caught after merge.
```

with:

```markdown
2. **Applied:** card-spec 8.2 is implemented as `hunt validate --against <rev>`
   and the scaffolded workflow runs it against `origin/main` on every pull
   request. It compares parsed cards, so a card that does not parse is left to
   snapshot validation rather than reported twice.
```

- [ ] In `/home/dotme/Code/hunt/docs/CODEBASE.md`, replace:

```markdown
- `new_parent(parent, name, tags, why)`, `new_run(run, run_date, previous_run,
  scope)`: fresh in-memory cards.
```

with:

```markdown
- `new_parent(parent, name, tags, why, cadence)`: a fresh parent, tagged with
  its category directory name unless the caller already supplied that tag.
- `new_run(run, run_date, previous_run, scope)`: a fresh run; `scope` is a list
  of items (a bare string is taken as one item).
```

- [ ] In `/home/dotme/Code/hunt/docs/CODEBASE.md`, replace:

```markdown
- `is_valid_tag/scope/date/task_name/parent_id/run_id`: pure predicates.
```

with:

```markdown
- `is_valid_tag/scope/scope_list/date/task_name/parent_id/run_id`: pure
  predicates.
```

- [ ] In `/home/dotme/Code/hunt/docs/CODEBASE.md`, in the `src/hunt/vault.py` section, add `resolve_revision(vault, revision)` to the function list, immediately before the `tracked_blobs` entry, as:

```markdown
- `resolve_revision(vault, revision)`: the commit a revision names, or a
  `VaultError`; used by `validate --against` so a typo is not an all-clear.
```

- [ ] Run `uv run pytest -q` and confirm 283 passed (the reference vault and the docs are both read by the suite).

- [ ] Commit:

```bash
git add TODO.md README.md docs/card-spec.md docs/vault-spec.md docs/CODEBASE.md
git commit -m "docs: card-spec v7, transition validation, category tags"
```
