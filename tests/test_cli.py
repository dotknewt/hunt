import os
import re
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

NAME = "Monthly encoded PowerShell persistence hunt"
DATE1 = "2026-07-31"
DATE2 = "2026-08-28"

FINDING_RE = re.compile(r"^(?P<path>\S+): (?P<code>[A-Za-z0-9_.-]+): \S.*$")


def hunt(vault, *args):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") and not k.startswith("HUNT_")
    }
    env["PYTHONPATH"] = str(SRC)
    env["HUNT_CONF"] = str(vault.conf)
    return subprocess.run(
        [sys.executable, "-m", "hunt", *args],
        cwd=str(vault.path),
        env=env,
        capture_output=True,
        text=True,
    )


def git(vault, *args):
    return subprocess.run(
        ["git", "-C", str(vault.path), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def commit_all(vault, message):
    git(vault, "add", "-A")
    git(
        vault,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        message,
    )


def subjects(vault):
    return git(vault, "log", "--format=%s").splitlines()


def staged_in_head(vault):
    out = git(vault, "show", "--name-only", "--format=", "HEAD")
    return sorted(line for line in out.splitlines() if line.strip())


def assert_clean(vault):
    assert git(vault, "status", "--porcelain") == ""
    assert git(vault, "rev-parse", "--abbrev-ref", "HEAD").strip() == vault.branch


def assert_file_conventions(path):
    data = path.read_bytes()
    assert data, f"{path} is empty"
    assert max(data) < 128, f"{path} contains a non-ASCII byte"
    assert b"\r" not in data, f"{path} contains CR"
    assert data.endswith(b"\n"), f"{path} has no trailing newline"
    assert not data.endswith(b"\n\n"), f"{path} has more than one trailing newline"


def assert_tree_conventions(vault):
    cards = sorted(vault.path.rglob("*.md"))
    assert cards
    for path in cards:
        assert_file_conventions(path)


def split_card(text):
    assert text.startswith("---\n"), "card does not open with a frontmatter fence"
    front, sep, body = text[4:].partition("\n---\n")
    assert sep, "card has no closing frontmatter fence"
    return front.splitlines(), body


def headings(text):
    return [line for line in text.splitlines() if line.startswith("#")]


def section(text, heading):
    lines = text.splitlines()
    start = lines.index(heading)
    out = []
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        if line.strip():
            out.append(line)
    return out


def card(vault, *parts):
    return vault.path.joinpath("hunt", "HNT-001", *parts)


def test_lifecycle(vault):
    base = len(subjects(vault))

    result = hunt(vault, "init")
    assert result.returncode == 0, result.stderr
    assert len(subjects(vault)) == base
    assert_clean(vault)

    result = hunt(vault, "new", "--category", "hunt", "--name", NAME)
    assert result.returncode == 0, result.stderr
    parent = card(vault, "HNT-001.md")
    assert parent.is_file()
    assert sorted(p.name for p in parent.parent.iterdir()) == ["HNT-001.md"]
    assert len(subjects(vault)) == base + 1
    assert subjects(vault)[0] == "hunt: new HNT-001"
    assert staged_in_head(vault) == ["hunt/HNT-001/HNT-001.md"]
    assert_clean(vault)

    text = parent.read_text()
    front, _ = split_card(text)
    assert "id: HNT-001" in front
    assert "category: HNT" in front
    assert "tags: []" in front
    assert "status: active" in front
    assert not [line for line in front if line.startswith("latest_run")]
    assert headings(text) == [
        f"# HNT-001 - {NAME}",
        "## Why",
        "## Latest findings",
        "## Run history",
    ]
    assert section(text, "## Latest findings") == []
    assert section(text, "## Run history") == []

    result = hunt(vault, "validate")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr == ""

    result = hunt(vault, "run", "--id", "HNT-001", "--date", DATE1)
    assert result.returncode == 0, result.stderr
    run1 = card(vault, "HNT-001.001.md")
    assert run1.is_file()
    assert len(subjects(vault)) == base + 2
    assert subjects(vault)[0] == "hunt: run HNT-001.001"
    assert staged_in_head(vault) == [
        "hunt/HNT-001/HNT-001.001.md",
        "hunt/HNT-001/HNT-001.md",
    ]
    assert_clean(vault)

    text1 = run1.read_text()
    front1, body1 = split_card(text1)
    assert "id: HNT-001.001" in front1
    assert "parent: HNT-001" in front1
    assert f'run_date: "{DATE1}"' in front1
    assert "status: open" in front1
    assert not [line for line in front1 if line.startswith("previous_run")]
    assert not [line for line in front1 if line.startswith("run_number")]
    assert body1.strip().splitlines()[0] == "Part of: [[HNT-001]]"
    assert "Previous:" not in text1
    assert headings(text1) == ["## Outcome"]

    text = parent.read_text()
    front, _ = split_card(text)
    assert "latest_run: HNT-001.001" in front
    assert f'latest_run_date: "{DATE1}"' in front
    assert section(text, "## Latest findings") == ["![[HNT-001.001#Outcome]]"]
    assert section(text, "## Run history") == [f"- [[HNT-001.001]] - {DATE1}"]

    result = hunt(vault, "validate")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    result = hunt(vault, "validate", "--id", "HNT-001")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""

    run1.write_text(text1.replace("status: open", "status: complete"))
    commit_all(vault, "mark HNT-001.001 complete")
    assert "status: complete" in run1.read_text()

    result = hunt(vault, "run", "--id", "HNT-001", "--date", DATE2)
    assert result.returncode == 0, result.stderr
    run2 = card(vault, "HNT-001.002.md")
    assert run2.is_file()
    assert subjects(vault)[0] == "hunt: run HNT-001.002"
    assert staged_in_head(vault) == [
        "hunt/HNT-001/HNT-001.002.md",
        "hunt/HNT-001/HNT-001.md",
    ]
    assert_clean(vault)

    text2 = run2.read_text()
    front2, body2 = split_card(text2)
    assert "id: HNT-001.002" in front2
    assert f'run_date: "{DATE2}"' in front2
    assert "previous_run: HNT-001.001" in front2
    assert "status: open" in front2
    assert body2.strip().splitlines()[:2] == [
        "Part of: [[HNT-001]]",
        "Previous: [[HNT-001.001]]",
    ]

    text = parent.read_text()
    front, _ = split_card(text)
    assert "latest_run: HNT-001.002" in front
    assert f'latest_run_date: "{DATE2}"' in front
    assert section(text, "## Latest findings") == ["![[HNT-001.002#Outcome]]"]
    assert section(text, "## Run history") == [
        f"- [[HNT-001.002]] - {DATE2}",
        f"- [[HNT-001.001]] - {DATE1}",
    ]

    result = hunt(vault, "validate")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr == ""

    assert subjects(vault)[:4] == [
        "hunt: run HNT-001.002",
        "mark HNT-001.001 complete",
        "hunt: run HNT-001.001",
        "hunt: new HNT-001",
    ]
    assert_tree_conventions(vault)


def test_new_does_not_create_a_run_card(vault):
    assert hunt(vault, "init").returncode == 0
    result = hunt(vault, "new", "--category", "hunt", "--name", NAME)
    assert result.returncode == 0, result.stderr

    parent_dir = card(vault)
    assert sorted(p.name for p in parent_dir.iterdir()) == ["HNT-001.md"]
    assert not list(parent_dir.glob("HNT-001.[0-9][0-9][0-9].md"))

    front, _ = split_card(card(vault, "HNT-001.md").read_text())
    assert not [line for line in front if line.startswith("latest_run")]

    result = hunt(vault, "validate")
    assert result.returncode == 0, result.stdout + result.stderr


def test_run_refuses_on_retired_parent(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "--category", "hunt", "--name", NAME).returncode == 0

    parent = card(vault, "HNT-001.md")
    parent.write_text(parent.read_text().replace("status: active", "status: retired"))
    commit_all(vault, "retire HNT-001")
    before = subjects(vault)

    result = hunt(vault, "run", "--id", "HNT-001", "--date", DATE1)
    assert result.returncode == 1
    assert result.stdout == ""
    assert len(result.stderr.strip().splitlines()) == 1
    assert "Traceback" not in result.stderr
    assert "retired" in result.stderr.lower()
    assert not card(vault, "HNT-001.001.md").exists()
    assert subjects(vault) == before
    assert_clean(vault)


def test_run_refuses_when_an_open_run_exists(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "--category", "hunt", "--name", NAME).returncode == 0
    assert hunt(vault, "run", "--id", "HNT-001", "--date", DATE1).returncode == 0
    assert "status: open" in card(vault, "HNT-001.001.md").read_text()
    before = subjects(vault)

    result = hunt(vault, "run", "--id", "HNT-001", "--date", DATE2)
    assert result.returncode == 1
    assert result.stdout == ""
    assert len(result.stderr.strip().splitlines()) == 1
    assert "Traceback" not in result.stderr
    assert "open" in result.stderr.lower()
    assert not card(vault, "HNT-001.002.md").exists()
    assert subjects(vault) == before
    assert_clean(vault)


def test_validate_reports_findings_on_broken_tree(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "--category", "hunt", "--name", NAME).returncode == 0
    assert hunt(vault, "run", "--id", "HNT-001", "--date", DATE1).returncode == 0
    assert hunt(vault, "validate").returncode == 0

    parent = card(vault, "HNT-001.md")
    parent.write_text(parent.read_text().replace("status: active\n", "status: active\nbogus: 1\n", 1))
    commit_all(vault, "break HNT-001")

    result = hunt(vault, "validate")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    lines = result.stdout.splitlines()
    assert lines
    matches = [FINDING_RE.match(line) for line in lines]
    assert all(matches), lines
    assert any("HNT-001.md" in m.group("path") for m in matches)


def test_domain_error_is_one_stderr_line(vault):
    assert hunt(vault, "init").returncode == 0

    result = hunt(vault, "run", "--id", "HNT-404", "--date", DATE1)
    assert result.returncode == 1
    assert result.stdout == ""
    assert len(result.stderr.strip().splitlines()) == 1
    assert "Traceback" not in result.stderr
    assert "HNT-404" in result.stderr


def test_bad_flags_exit_2(vault):
    result = hunt(vault, "new", "--category", "hunt", "--name", NAME, "--bogus")
    assert result.returncode == 2
    assert "usage" in result.stderr.lower()

    result = hunt(vault, "new", "--category", "hunt")
    assert result.returncode == 2

    result = hunt(vault, "frobnicate")
    assert result.returncode == 2


def test_no_args_prints_help_and_exits_0(vault):
    result = hunt(vault)
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()
    for name in ("init", "new", "run", "validate"):
        assert name in result.stdout
