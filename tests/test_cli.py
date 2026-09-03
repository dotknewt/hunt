import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

NAME = "Monthly encoded PowerShell persistence hunt"
DATE1 = "2026-07-31"
DATE2 = "2026-08-28"

FINDING_RE = re.compile(r"^(?P<path>\S+): (?P<code>[A-Za-z0-9_.-]+): \S.*$")

# vault-spec 5 lists these normatively; `hunt init` writes exactly them.
SCAFFOLD = (
    ".gitattributes",
    ".gitignore",
    ".obsidian/app.json",
    ".obsidian/core-plugins.json",
    ".obsidian/types.json",
)


def run_hunt(*args, cwd, conf=None, **env_extra):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") and not k.startswith("HUNT_")
    }
    env["PYTHONPATH"] = str(SRC)
    if conf is not None:
        env["HUNT_CONF"] = str(conf)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "hunt", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )


def hunt(vault, *args):
    return run_hunt(*args, cwd=vault.path, conf=vault.conf)


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
    # The scaffold lives in the vault too, and vault-spec 8 does not exempt it.
    scaffolded = [vault.path / name for name in SCAFFOLD]
    assert any(path.is_file() for path in scaffolded)
    for path in cards + [path for path in scaffolded if path.is_file()]:
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
    # This vault already has .gitattributes and main, so the rest of the
    # scaffold lands in one commit on the working branch.
    assert len(subjects(vault)) == base + 1
    assert subjects(vault)[0] == "hunt: init"
    assert staged_in_head(vault) == [
        ".gitignore",
        ".obsidian/app.json",
        ".obsidian/core-plugins.json",
        ".obsidian/types.json",
    ]
    assert_clean(vault)
    base = len(subjects(vault))

    # Idempotent: a second run finds the scaffold in place and writes nothing.
    assert hunt(vault, "init").returncode == 0
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

    # --name is optional (it defaults to the parent id), so --id is the
    # missing-required-argument case now.
    result = hunt(vault, "run")
    assert result.returncode == 2

    result = hunt(vault, "frobnicate")
    assert result.returncode == 2


def test_no_args_prints_help_and_exits_0(vault):
    result = hunt(vault)
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()
    for name in ("init", "new", "run", "validate", "completion"):
        assert name in result.stdout
    assert "__complete" not in result.stdout


# --- an unconfigured hunt.conf instructs instead of breaking (vault-spec 1.2) -


def empty_conf(tmp_path):
    conf = tmp_path / "hunt.conf"
    conf.write_text('VAULT_PATH=""\nVAULT_BRANCH=""\n')
    return conf


def test_unset_config_instructs_and_exits_2(tmp_path):
    conf = empty_conf(tmp_path)
    result = run_hunt("new", "--category", "hunt", cwd=tmp_path, conf=conf)
    assert result.returncode == 2, result.stderr
    assert "VAULT_PATH" in result.stderr
    assert "VAULT_BRANCH" in result.stderr
    assert str(conf) in result.stderr
    assert "hunt init" in result.stderr
    assert "Traceback" not in result.stderr


def test_unset_config_does_not_stop_help_or_completion(tmp_path):
    conf = empty_conf(tmp_path)
    for args in (("--help",), ("completion", "zsh"), ("__complete", "ids")):
        result = run_hunt(*args, cwd=tmp_path, conf=conf)
        assert result.returncode == 0, (args, result.stderr)
        assert "Traceback" not in result.stderr


def test_the_repo_ships_an_unconfigured_conf(tmp_path):
    """The values tracked on main are empty, and the CLI must still run."""
    repo_conf = Path(__file__).resolve().parents[1] / "hunt.conf"
    result = run_hunt("validate", cwd=tmp_path, conf=repo_conf)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "VAULT_PATH" in result.stderr


# --- category spellings and the default title (card-spec 4) --------------------


@pytest.mark.parametrize("spelling", ["h", "H", "hunt", "HNT", "hnt", "Hunt"])
def test_every_category_spelling_reaches_the_same_directory(vault, spelling):
    result = hunt(vault, "new", "-c", spelling, "--name", NAME)
    assert result.returncode == 0, result.stderr
    assert (vault.path / "hunt" / "HNT-001" / "HNT-001.md").is_file()


def test_new_without_a_name_titles_the_card_after_its_id(vault):
    result = hunt(vault, "new", "-c", "h")
    assert result.returncode == 0, result.stderr
    card = (vault.path / "hunt" / "HNT-001" / "HNT-001.md").read_text()
    assert "# HNT-001 - HNT-001" in card
    assert hunt(vault, "validate").returncode == 0


def test_unknown_category_lists_every_accepted_spelling(vault):
    result = hunt(vault, "new", "-c", "nope")
    assert result.returncode == 2
    for spelling in ("baseline", "BSL", "b", "hunt", "HNT", "h", "math", "MTH", "m"):
        assert spelling in result.stderr


# --- completion (shtab) -------------------------------------------------------


@pytest.mark.parametrize("shell", ["zsh", "bash", "powershell"])
def test_completion_script_wires_the_dynamic_helpers(vault, shell):
    result = hunt(vault, "completion", shell)
    assert result.returncode == 0, result.stderr
    assert "--category" in result.stdout
    assert "hunt __complete categories" in result.stdout
    assert "hunt __complete ids" in result.stdout
    for command in ("init", "new", "run", "validate", "completion"):
        assert command in result.stdout
    # The hidden subcommand is a completion helper, not something to complete to.
    assert "__complete categories" in result.stdout  # the helper call, and only that
    assert result.stdout.count("__complete") == 2


def test_completion_rejects_an_unsupported_shell(vault):
    assert hunt(vault, "completion", "csh").returncode == 2


def test_hidden_complete_lists_categories_and_ids(vault):
    result = hunt(vault, "__complete", "categories")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [
        "baseline",
        "hunt",
        "math",
        "BSL",
        "HNT",
        "MTH",
        "b",
        "h",
        "m",
    ]

    assert hunt(vault, "__complete", "ids").stdout == ""
    assert hunt(vault, "new", "-c", "h").returncode == 0
    assert hunt(vault, "new", "-c", "m").returncode == 0
    result = hunt(vault, "__complete", "ids")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["HNT-001", "MTH-001"]


def test_hidden_complete_stays_silent_when_nothing_is_configured(tmp_path):
    """A completer that prints a diagnostic prints it into the user's prompt."""
    for conf in (empty_conf(tmp_path), tmp_path / "absent.conf"):
        result = run_hunt("__complete", "ids", cwd=tmp_path, conf=conf)
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert result.stderr == ""


# --- init writes hunt.conf and scaffolds a fresh vault (vault-spec 1.2, 5) ----

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "hunt tests",
    "GIT_AUTHOR_EMAIL": "tests@example.invalid",
    "GIT_COMMITTER_NAME": "hunt tests",
    "GIT_COMMITTER_EMAIL": "tests@example.invalid",
}


def init_in(tmp_path, *args, conf=None, **env_extra):
    """`hunt init` in a directory with no vault, carrying a git identity.

    run_hunt scrubs GIT_* so a test cannot inherit the developer's git
    environment, which also removes the identity the root commit needs.
    """
    return run_hunt("init", *args, cwd=tmp_path, conf=conf, **GIT_IDENTITY, **env_extra)


def read_conf(tmp_path):
    return (tmp_path / "hunt.conf").read_text()


def test_init_populates_an_empty_conf_and_scaffolds_the_root_commit(tmp_path):
    conf = empty_conf(tmp_path)
    vault_path = tmp_path / "vault"
    result = init_in(
        tmp_path,
        "--vault-path",
        str(vault_path),
        "--vault-branch",
        "drafting",
        conf=conf,
    )
    assert result.returncode == 0, result.stderr
    assert 'VAULT_PATH="%s"' % vault_path in conf.read_text()
    assert 'VAULT_BRANCH="drafting"' in conf.read_text()

    def git_in(*args):
        return subprocess.run(
            ["git", "-C", str(vault_path), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    # vault-spec 8: the LF guarantee has to be in force before the first card,
    # so the scaffold is in the root commit on main, not on the working branch.
    assert sorted(git_in("ls-tree", "-r", "--name-only", "main").split()) == sorted(
        SCAFFOLD
    )
    assert git_in("rev-parse", "--abbrev-ref", "HEAD").strip() == "drafting"
    assert git_in("log", "--format=%s").splitlines() == ["hunt: init"]
    assert git_in("status", "--porcelain") == ""
    for name in SCAFFOLD:
        assert_file_conventions(vault_path / name)


def test_init_creates_a_conf_where_none_was_found(tmp_path):
    result = init_in(
        tmp_path,
        "--vault-path",
        str(tmp_path / "vault"),
        "--vault-branch",
        "drafting",
    )
    assert result.returncode == 0, result.stderr
    assert 'VAULT_BRANCH="drafting"' in read_conf(tmp_path)


def test_init_refuses_when_hunt_conf_is_pointed_at_a_missing_file(tmp_path):
    """An explicit pointer at a missing file is a mistake, not a create request."""
    result = init_in(
        tmp_path,
        "--vault-path",
        str(tmp_path / "vault"),
        "--vault-branch",
        "drafting",
        conf=tmp_path / "absent.conf",
    )
    assert result.returncode == 1
    assert "absent.conf" in result.stderr
    assert not (tmp_path / "hunt.conf").exists()


def test_init_without_flags_and_without_a_conf_instructs(tmp_path):
    result = init_in(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "hunt.conf" in result.stderr
    assert "--vault-path" in result.stderr
    assert not (tmp_path / "hunt.conf").exists()


def test_init_refuses_when_only_one_key_ends_up_set(tmp_path):
    conf = empty_conf(tmp_path)
    result = init_in(tmp_path, "--vault-path", str(tmp_path / "vault"), conf=conf)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "VAULT_BRANCH" in result.stderr
    # The value given was still recorded: refusing is not a reason to lose it.
    assert 'VAULT_PATH="%s"' % (tmp_path / "vault") in conf.read_text()
    assert not (tmp_path / "vault" / ".git").exists()


def test_init_refuses_to_overwrite_a_configured_value_without_yes(vault):
    before = vault.conf.read_text()
    result = hunt(vault, "init", "--vault-branch", "other")
    assert result.returncode == 1
    assert "refusing to overwrite VAULT_BRANCH" in result.stderr
    assert "--yes" in result.stderr
    assert vault.conf.read_text() == before


def test_init_overwrites_a_configured_value_with_yes(vault):
    result = hunt(vault, "init", "--vault-branch", "other", "--yes")
    assert result.returncode == 0, result.stderr
    assert 'VAULT_BRANCH="other"' in vault.conf.read_text()
    assert git(vault, "rev-parse", "--abbrev-ref", "HEAD").strip() == "other"


def test_init_repeating_the_configured_value_is_not_an_overwrite(vault):
    result = hunt(vault, "init", "--vault-branch", vault.branch)
    assert result.returncode == 0, result.stderr
    assert 'VAULT_BRANCH="%s"' % vault.branch in vault.conf.read_text()


def test_init_warns_and_survives_a_gitignore_that_hides_the_scaffold(vault):
    vault.write(".gitignore", ".obsidian/\n")
    commit_all(vault, "hand-rolled gitignore")

    result = hunt(vault, "init")
    assert result.returncode == 0, result.stderr
    assert "warning" in result.stderr
    assert ".obsidian/app.json" in result.stderr
    # Skipped, not force-added: an ignored path would leave the tree dirty.
    assert not (vault.path / ".obsidian").exists()
    assert_clean(vault)


# --- environment artifacts (vault-spec 3) ------------------------------------


def test_ds_store_anywhere_is_neither_a_finding_nor_a_blocker(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h").returncode == 0
    for relative in (".DS_Store", "hunt/.DS_Store", "hunt/HNT-001/Thumbs.db"):
        (vault.path / relative).write_bytes(b"\x00finder\r\n")

    result = hunt(vault, "validate")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    # validate is read-only: it ignores them, it does not delete them.
    assert (vault.path / ".DS_Store").exists()

    result = hunt(vault, "new", "-c", "m")
    assert result.returncode == 0, result.stderr
    assert "removed" in result.stdout
    for relative in (".DS_Store", "hunt/.DS_Store", "hunt/HNT-001/Thumbs.db"):
        assert not (vault.path / relative).exists()
    assert staged_in_head(vault) == ["math/MTH-001/MTH-001.md"]
    assert_clean(vault)


# --- CRLF never reaches a branch (vault-spec 8) ------------------------------


def test_a_card_committed_with_crlf_is_a_finding(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h").returncode == 0

    # Defeat .gitattributes the only way a repo can: remove it, then commit CR.
    parent = card(vault, "HNT-001.md")
    (vault.path / ".gitattributes").unlink()
    parent.write_bytes(parent.read_bytes().replace(b"\n", b"\r\n"))
    commit_all(vault, "windows happened")

    result = hunt(vault, "validate")
    assert result.returncode == 1
    codes = {m.group("code") for m in map(FINDING_RE.match, result.stdout.splitlines())}
    assert "bytes.crlf-committed" in codes
    assert "path.missing-gitattributes" in codes


def test_the_tool_refuses_to_commit_a_staged_crlf_card(vault):
    """Layer 3: hunt itself can never be the thing that records a CRLF card."""
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h").returncode == 0
    (vault.path / ".gitattributes").unlink()
    commit_all(vault, "drop the guarantee")

    target = card(vault, "HNT-001.md")
    target.write_bytes(b"---\r\n")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from hunt import vault as v; "
            "v.commit(sys.argv[1], [sys.argv[2]], 'hunt: bad')",
            str(vault.path),
            str(target),
        ],
        env={**os.environ, "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "CR" in result.stderr or "carriage" in result.stderr
    # The refusal unstages what it staged, so the index is where it started.
    assert git(vault, "diff", "--cached", "--name-only") == ""


# --- validate: the root-file exemption must not drift ------------------------


def test_a_gitignore_inside_a_category_is_still_a_stray_file(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h").returncode == 0
    vault.write("hunt/.gitignore", "*\n")

    result = hunt(vault, "validate")
    assert result.returncode == 1
    codes = {m.group("code") for m in map(FINDING_RE.match, result.stdout.splitlines())}
    assert "path.stray-file" in codes


def test_a_gitignore_that_hides_a_card_is_a_finding(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h").returncode == 0
    vault.write(".gitignore", "HNT-001.md\n")
    commit_all(vault, "hide a card")

    result = hunt(vault, "validate")
    assert result.returncode == 1
    codes = {m.group("code") for m in map(FINDING_RE.match, result.stdout.splitlines())}
    assert "path.gitignore-hides-card" in codes


# --- run scope ---------------------------------------------------------------


def test_run_records_a_scope_when_given(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h", "--name", NAME).returncode == 0
    result = hunt(
        vault, "run", "--id", "HNT-001", "--date", DATE1, "--scope", "windows servers"
    )
    assert result.returncode == 0, result.stderr

    front, _ = split_card(card(vault, "HNT-001.001.md").read_text())
    assert front[-1] == 'scope: "windows servers"', "scope is the last key"
    assert hunt(vault, "validate").returncode == 0
    assert_clean(vault)


def test_run_omits_scope_when_not_given(vault):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h", "--name", NAME).returncode == 0
    assert hunt(vault, "run", "--id", "HNT-001", "--date", DATE1).returncode == 0

    front, _ = split_card(card(vault, "HNT-001.001.md").read_text())
    assert not [line for line in front if line.startswith("scope")]
    assert hunt(vault, "validate").returncode == 0


@pytest.mark.parametrize("scope", ["", " windows", 'say "windows"', "back\\slash"])
def test_run_rejects_a_malformed_scope(vault, scope):
    assert hunt(vault, "init").returncode == 0
    assert hunt(vault, "new", "-c", "h", "--name", NAME).returncode == 0
    result = hunt(vault, "run", "--id", "HNT-001", "--date", DATE1, "--scope", scope)
    assert result.returncode == 2
    assert "invalid scope" in result.stderr
    assert not card(vault, "HNT-001.001.md").exists()
