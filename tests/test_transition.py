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
