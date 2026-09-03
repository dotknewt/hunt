import shutil
from pathlib import Path

import pytest

from hunt.validate import validate_vault

REFERENCES = Path(__file__).resolve().parents[1] / "docs" / "references" / "task-cards"

BSL = "baseline/BSL-001/BSL-001.md"
RUN1 = "baseline/BSL-001/BSL-001.001.md"
RUN2 = "baseline/BSL-001/BSL-001.002.md"


@pytest.fixture
def good(vault):
    """The 9 reference fixtures laid out as a real vault."""
    for entry in REFERENCES.iterdir():
        shutil.copytree(entry, vault.path / entry.name)
    return vault


def codes(vault_path):
    return sorted(finding.code for finding in validate_vault(vault_path))


def edit(vault, relative, old, new, count=1):
    path = vault.path / relative
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {relative}"
    path.write_text(text.replace(old, new, count), encoding="utf-8")
    return path


def test_the_reference_vault_validates_clean(good):
    assert validate_vault(good.path) == []


def test_a_missing_vault_is_reported(vault, tmp_path):
    assert codes(tmp_path / "nope") == ["path.missing-vault"]


# --- bytes -------------------------------------------------------------------


def test_non_ascii_byte(good):
    edit(good, RUN1, "Initial baseline", "Initial baseline\u2014")
    assert "bytes.non-ascii" in codes(good.path)


def test_em_dash_where_a_hyphen_belongs(good):
    """The H1 separator is a plain hyphen; an em dash is a non-ASCII byte."""
    edit(good, BSL, "# BSL-001 - Monthly", "# BSL-001 \u2014 Monthly")
    assert "bytes.non-ascii" in codes(good.path)


def test_crlf(good):
    path = good.path / RUN1
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert "bytes.crlf" in codes(good.path)


def test_missing_trailing_newline(good):
    path = good.path / RUN1
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    assert "bytes.no-trailing-newline" in codes(good.path)


def test_extra_trailing_newline(good):
    path = good.path / RUN1
    path.write_bytes(path.read_bytes() + b"\n")
    assert "bytes.extra-trailing-newline" in codes(good.path)


def test_trailing_whitespace(good):
    edit(good, RUN1, "## Outcome\n", "## Outcome   \n")
    assert "bytes.trailing-whitespace" in codes(good.path)


# --- frontmatter -------------------------------------------------------------


def test_unquoted_date(good):
    edit(good, RUN1, 'run_date: "2026-08-01"', "run_date: 2026-08-01")
    assert "frontmatter.unquoted-date" in codes(good.path)


def test_unknown_key(good):
    edit(good, RUN1, "status: complete\n", "status: complete\nmood: cheerful\n")
    assert "frontmatter.unknown-key" in codes(good.path)


def test_missing_required_key(good):
    edit(good, RUN1, "status: complete\n", "")
    assert "frontmatter.missing-key" in codes(good.path)


def test_duplicate_key(good):
    edit(good, RUN1, "status: complete\n", "status: complete\nstatus: complete\n")
    assert "frontmatter.duplicate-key" in codes(good.path)


def test_bad_status_value(good):
    edit(good, RUN1, "status: complete", "status: finished")
    assert "frontmatter.bad-status" in codes(good.path)


def test_id_does_not_match_the_path(good):
    edit(good, RUN1, "id: BSL-001.001", "id: BSL-001.009")
    found = codes(good.path)
    assert "frontmatter.id-path-mismatch" in found or "frontmatter.bad-id" in found


def test_key_order(good):
    edit(good, RUN1, "id: BSL-001.001\nparent: BSL-001\n", "parent: BSL-001\nid: BSL-001.001\n")
    assert "frontmatter.key-order" in codes(good.path)


def test_latest_run_present_on_a_run_less_parent(good):
    """card-spec 5.1: the two pointers are absent when the parent has no runs."""
    (good.path / RUN1).unlink()
    (good.path / RUN2).unlink()
    assert set(codes(good.path)) & {
        "invariant.chain-broken",
        "frontmatter.bad-run-ref",
        "render.mismatch",
    }


# --- layout ------------------------------------------------------------------


def test_stray_markdown(good):
    (good.path / "baseline" / "BSL-001" / "notes.md").write_text("x\n", encoding="utf-8")
    assert "path.stray-markdown" in codes(good.path)


def test_stray_non_markdown_file(good):
    (good.path / "baseline" / "BSL-001" / "chart.png").write_bytes(b"\x89PNG\n")
    assert "path.stray-file" in codes(good.path)


def test_unknown_category_directory(good):
    (good.path / "sideways").mkdir()
    (good.path / "sideways" / "keep.md").write_text("x\n", encoding="utf-8")
    assert "path.unknown-category-dir" in codes(good.path)


def test_parent_directory_missing_its_index(good):
    (good.path / BSL).unlink()
    assert "path.missing-index" in codes(good.path)


def test_case_colliding_stems(good):
    """A stem must be unique vault-wide, case-insensitively: macOS collides them."""
    target = good.path / "math" / "MTH-001" / "bsl-001.md"
    target.write_text((good.path / BSL).read_text(encoding="utf-8"), encoding="utf-8")
    assert "path.stem-collision" in codes(good.path)


# --- cross-file invariants ---------------------------------------------------


def test_broken_previous_run_chain(good):
    """Frontmatter and body agree with each other but point at a run that is not
    the immediate predecessor, so only the cross-file check can catch it."""
    edit(good, RUN2, "previous_run: BSL-001.001", "previous_run: BSL-001.009")
    edit(good, RUN2, "Previous: [[BSL-001.001]]", "Previous: [[BSL-001.009]]")
    assert set(codes(good.path)) & {
        "invariant.chain-broken",
        "frontmatter.bad-run-ref",
        "invariant.link-target",
    }


def test_previous_run_disagreeing_with_the_body_is_caught(good):
    edit(good, RUN2, "previous_run: BSL-001.001", "previous_run: BSL-001.009")
    assert "render.missing-previous" in codes(good.path)


def test_run_number_gap(good):
    (good.path / RUN1).rename(good.path / "baseline" / "BSL-001" / "BSL-001.003.md")
    assert set(codes(good.path)) & {"invariant.number-gap", "frontmatter.id-path-mismatch"}


def test_latest_run_points_at_the_wrong_run(good):
    edit(good, BSL, "latest_run: BSL-001.002", "latest_run: BSL-001.001")
    assert "render.mismatch" in codes(good.path)


def test_two_open_runs_in_one_parent(good):
    edit(good, RUN1, "status: complete", "status: open")
    edit(good, RUN2, "status: complete", "status: open")
    assert "invariant.multiple-open" in codes(good.path)


def test_one_open_run_is_allowed(good):
    edit(good, RUN2, "status: complete", "status: open")
    assert "invariant.multiple-open" not in codes(good.path)


def test_link_direction_to_another_parents_run(good):
    """A link leaving its own parent directory must target the parent index."""
    edit(good, BSL, "## Why\n", "## Why\nSee [[HNT-001.001]].\n")
    assert "invariant.link-direction" in codes(good.path)


def test_aliased_link_is_rejected(good):
    edit(good, BSL, "## Why\n", "## Why\nSee [[HNT-001|the hunt]].\n")
    assert "invariant.link-alias" in codes(good.path)


# --- body structure ----------------------------------------------------------


def test_missing_section(good):
    edit(good, BSL, "## Latest findings\n", "")
    assert set(codes(good.path)) & {"render.missing-section", "render.parse-error"}


def test_bad_h1(good):
    edit(good, BSL, "# BSL-001 - Monthly", "# BSL-001 Monthly")
    assert set(codes(good.path)) & {"render.bad-h1", "render.parse-error"}


def test_missing_part_of_line(good):
    edit(good, RUN1, "Part of: [[BSL-001]]\n", "")
    assert set(codes(good.path)) & {"render.missing-part-of", "render.parse-error"}


def test_first_run_must_not_carry_a_previous_line(good):
    edit(good, RUN1, "Part of: [[BSL-001]]\n", "Part of: [[BSL-001]]\nPrevious: [[BSL-001.000]]\n")
    assert set(codes(good.path)) & {
        "render.forbidden-previous",
        "render.parse-error",
        "invariant.link-target",
    }


def test_an_empty_card_has_its_own_code(good):
    """The code must not contradict the message: an empty file is not the same
    condition as a missing trailing newline."""
    (good.path / RUN1).write_bytes(b"")
    assert "bytes.empty-file" in codes(good.path)
