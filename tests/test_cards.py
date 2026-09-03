import datetime
from pathlib import Path

import pytest

from hunt import cards
from hunt.cards import CardError

REFERENCES = Path(__file__).resolve().parents[1] / "docs" / "references" / "task-cards"
PARENTS = ("baseline/BSL-001", "hunt/HNT-001", "math/MTH-001")

PARENT_NO_RUNS = """---
id: BSL-002
category: BSL
tags: []
status: active
---

# BSL-002 - A task with no runs yet

## Why

## Latest findings

## Run history
"""


def reference_files():
    return sorted(REFERENCES.rglob("*.md"))


def load_reference_parent(relative):
    directory = REFERENCES / relative
    name = directory.name
    parent = cards.parse_parent((directory / f"{name}.md").read_text(encoding="utf-8"))
    runs = [
        cards.parse_run(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob(f"{name}.[0-9][0-9][0-9].md"))
    ]
    return parent, runs


def test_reference_fixtures_are_present():
    assert len(reference_files()) == 9


@pytest.mark.parametrize("path", reference_files(), ids=lambda p: p.name)
def test_golden_round_trip_is_byte_identical(path):
    """Every fixture must survive parse -> render unchanged, byte for byte."""
    original = path.read_text(encoding="utf-8")
    if cards.is_valid_parent_id(path.stem):
        card = cards.parse_parent(original)
        directory = path.parent
        runs = [
            cards.parse_run(run.read_text(encoding="utf-8"))
            for run in sorted(directory.glob(f"{directory.name}.[0-9][0-9][0-9].md"))
        ]
        rendered = cards.render_parent(card, runs)
    else:
        rendered = cards.render_run(cards.parse_run(original))
    assert rendered == original


def test_reference_files_are_ascii_lf_single_trailing_newline():
    for path in reference_files():
        data = path.read_bytes()
        assert b"\r" not in data, path
        assert all(byte < 128 for byte in data), path
        assert data.endswith(b"\n") and not data.endswith(b"\n\n"), path


# --- run-less parents -------------------------------------------------------


def test_new_parent_has_no_latest_run_keys():
    parent = cards.new_parent("BSL-002", "A task with no runs yet")
    text = cards.render_parent(parent, [])
    assert "latest_run" not in text
    assert "latest_run_date" not in text
    assert text == PARENT_NO_RUNS.replace(
        "## Why\n", "## Why\n"
    ).replace("# BSL-002 - A task with no runs yet", "# BSL-002 - A task with no runs yet")


def test_run_less_parent_round_trips():
    assert cards.render_parent(cards.parse_parent(PARENT_NO_RUNS), []) == PARENT_NO_RUNS


def test_adding_first_run_to_a_run_less_parent():
    parent = cards.parse_parent(PARENT_NO_RUNS)
    run = cards.new_run("BSL-002.001", "2026-09-01")
    text = cards.render_parent(parent, [run])
    assert "latest_run: BSL-002.001" in text
    assert 'latest_run_date: "2026-09-01"' in text
    assert "![[BSL-002.001#Outcome]]" in text
    assert "- [[BSL-002.001]] - 2026-09-01" in text


def test_adding_a_run_to_a_parent_that_already_has_runs():
    parent, runs = load_reference_parent("baseline/BSL-001")
    new = cards.new_run("BSL-001.003", "2026-09-30", "BSL-001.002")
    text = cards.render_parent(parent, runs + [new])
    assert "latest_run: BSL-001.003" in text
    history = [line for line in text.splitlines() if line.startswith("- [[")]
    assert history == [
        "- [[BSL-001.003]] - 2026-09-30",
        "- [[BSL-001.002]] - 2026-08-31",
        "- [[BSL-001.001]] - 2026-08-01",
    ], "run history is newest first, one line per run"


# --- the user region --------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        "## Appendix\nKeep me.\n",
        "### Operator notes\nKeep this.\n",
        "## Appendix\nKeep me.\n\n### Nested\nAlso me.\n",
    ],
)
def test_user_sections_after_run_history_survive_a_re_render(extra):
    """card-spec 5.2 puts every H2-or-deeper section after Run history in the
    user region, so a re-render must copy it verbatim."""
    parent, runs = load_reference_parent("baseline/BSL-001")
    original = (REFERENCES / "baseline/BSL-001/BSL-001.md").read_text(encoding="utf-8")
    source = original.rstrip("\n") + "\n\n" + extra
    assert cards.render_parent(cards.parse_parent(source), runs) == source


def test_why_body_survives_a_re_render():
    parent, runs = load_reference_parent("hunt/HNT-001")
    assert "Encoded PowerShell" in parent.why
    assert parent.why in cards.render_parent(parent, runs)


def test_a_heading_between_the_required_sections_is_rejected():
    source = PARENT_NO_RUNS.replace(
        "## Latest findings", "### Sneaky\n\n## Latest findings", 1
    )
    with pytest.raises(CardError):
        cards.parse_parent(source)


# --- run status -------------------------------------------------------------


def test_new_run_is_open_never_complete():
    """Only a human sets complete; the tool must not (card-spec 6.1)."""
    run = cards.new_run("BSL-002.001", "2026-09-01")
    assert run.status == cards.STATUS_OPEN


@pytest.mark.parametrize("status", ["open", "complete", "void"])
def test_every_run_status_round_trips(status):
    run = cards.new_run("BSL-002.001", "2026-09-01")
    run.frontmatter["status"] = status
    text = cards.render_run(run)
    assert f"status: {status}\n" in text
    assert cards.render_run(cards.parse_run(text)) == text


def test_first_run_has_no_previous_run_and_no_previous_line():
    text = cards.render_run(cards.new_run("BSL-002.001", "2026-09-01"))
    assert "previous_run" not in text
    assert "Previous:" not in text


def test_first_run_rejects_a_predecessor():
    with pytest.raises(CardError):
        cards.new_run("BSL-002.001", "2026-09-01", "BSL-002.000")


def test_later_run_carries_previous_run_and_previous_line():
    text = cards.render_run(cards.new_run("BSL-002.002", "2026-09-02", "BSL-002.001"))
    assert "previous_run: BSL-002.001\n" in text
    assert "Previous: [[BSL-002.001]]\n" in text


# --- identifiers and allocation ---------------------------------------------


def test_run_number_comes_from_the_filename_not_frontmatter():
    assert cards.run_number_from_filename(Path("BSL-001.002.md")) == 2
    with pytest.raises(CardError):
        cards.run_number_from_filename(Path("BSL-001.md"))
    text = cards.render_run(cards.new_run("BSL-001.002", "2026-08-31", "BSL-001.001"))
    assert "run_number" not in text


def test_ids_are_zero_padded():
    assert cards.parent_id("hunt", 7) == "HNT-007"
    assert cards.run_id("HNT-007", 3) == "HNT-007.003"


def test_category_resolves_from_code_or_directory():
    assert cards.resolve_category("hunt") == "HNT"
    assert cards.resolve_category("HNT") == "HNT"
    with pytest.raises(CardError):
        cards.resolve_category("nope")


def write_parent(vault, category, ident):
    directory = vault.path / category / ident
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{ident}.md").write_text(
        cards.render_parent(cards.new_parent(ident, "A task"), []), encoding="utf-8"
    )
    return directory


def test_next_parent_number_is_max_plus_one(vault):
    assert cards.next_parent_number(vault.path, "HNT") == 1
    write_parent(vault, "hunt", "HNT-001")
    assert cards.next_parent_number(vault.path, "HNT") == 2


def test_next_run_number_is_max_plus_one(vault):
    directory = write_parent(vault, "hunt", "HNT-001")
    assert cards.next_run_number(vault.path, "HNT-001") == 1
    (directory / "HNT-001.001.md").write_text(
        cards.render_run(cards.new_run("HNT-001.001", "2026-09-01")), encoding="utf-8"
    )
    assert cards.next_run_number(vault.path, "HNT-001") == 2


def test_allocation_refuses_over_a_gap(vault):
    """vault-spec 7: a gap means the tree already violates card-spec 7 invariant
    2, so the tool refuses rather than allocating into or past it."""
    write_parent(vault, "hunt", "HNT-001")
    write_parent(vault, "hunt", "HNT-003")
    with pytest.raises(CardError, match="refusing to allocate"):
        cards.next_parent_number(vault.path, "HNT")


def test_allocation_refuses_a_case_collision():
    """Tested directly on the name list: a case-insensitive filesystem (macOS)
    cannot hold both entries at once, but a case-sensitive one can."""
    with pytest.raises(CardError, match="differ only in case"):
        cards._check_case_collision(["HNT-001", "hnt-001"], "category HNT")


def test_names_differing_by_more_than_case_are_fine():
    cards._check_case_collision(["HNT-001", "HNT-002"], "category HNT")


def test_numbers_above_999_are_refused():
    with pytest.raises(CardError):
        cards.parent_id("HNT", 1000)
    with pytest.raises(CardError):
        cards.run_id("HNT-001", 1000)


# --- frontmatter parsing ----------------------------------------------------


def test_duplicate_frontmatter_key_is_rejected():
    source = PARENT_NO_RUNS.replace("status: active\n", "status: active\nstatus: active\n", 1)
    with pytest.raises(CardError):
        cards.parse_parent(source)


def test_an_unquoted_date_parses_as_a_date_object_not_a_string():
    """Load-bearing: it is how the validator detects the card-spec 4 violation.
    A loader that made quoted and unquoted dates indistinguishable would hide it."""
    source = """---
id: BSL-002.001
parent: BSL-002
run_date: 2026-09-01
status: open
---

Part of: [[BSL-002]]

## Outcome
"""
    block, _ = cards.split_frontmatter(source)
    frontmatter = cards._load_frontmatter(block)
    assert isinstance(frontmatter["run_date"], datetime.date)
    assert not isinstance(frontmatter["run_date"], str)


def test_a_quoted_date_parses_as_a_string():
    block, _ = cards.split_frontmatter(PARENT_NO_RUNS)
    parent, runs = load_reference_parent("baseline/BSL-001")
    assert isinstance(parent.frontmatter["latest_run_date"], str)


def test_exactly_one_h1_is_required():
    source = PARENT_NO_RUNS.replace(
        "# BSL-002 - A task with no runs yet",
        "# BSL-002 - A task with no runs yet\n\n# BSL-002 - second h1",
        1,
    )
    with pytest.raises(CardError):
        cards.parse_parent(source)


def test_a_run_without_an_outcome_section_is_rejected():
    source = """---
id: BSL-002.001
parent: BSL-002
run_date: "2026-09-01"
status: open
---

Part of: [[BSL-002]]

## Findings
"""
    with pytest.raises(CardError):
        cards.parse_run(source)


def test_task_name_rules():
    assert cards.is_valid_task_name("A normal name")
    assert not cards.is_valid_task_name("")
    assert not cards.is_valid_task_name(" leading space")
    assert not cards.is_valid_task_name("trailing space ")
    assert not cards.is_valid_task_name("em dash \u2014 here")
