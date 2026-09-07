import os
from pathlib import Path

import pytest

from hunt import vault as vaultmod
from hunt.config import Config
from hunt.vault import VaultError

from conftest import run_git


def config_for(vault, branch=None):
    return Config(vault_path=vault.path, vault_branch=branch or vault.branch)


# --- ensure_writable, one test per precondition ------------------------------


def test_missing_vault_directory(vault, tmp_path):
    config = Config(vault_path=tmp_path / "nope", vault_branch=vault.branch)
    with pytest.raises(VaultError, match="does not exist"):
        vaultmod.ensure_writable(config)


def test_vault_path_is_not_a_directory(vault, tmp_path):
    target = tmp_path / "a-file"
    target.write_text("", encoding="utf-8")
    config = Config(vault_path=target, vault_branch=vault.branch)
    with pytest.raises(VaultError, match="does not exist"):
        vaultmod.ensure_writable(config)


def test_not_a_git_repository(vault, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    config = Config(vault_path=plain, vault_branch=vault.branch)
    with pytest.raises(VaultError, match="not a git repository"):
        vaultmod.ensure_writable(config)


def test_branch_does_not_exist(vault):
    with pytest.raises(VaultError, match="does not exist"):
        vaultmod.ensure_writable(config_for(vault, "no-such-branch"))


def test_a_different_branch_is_checked_out(vault):
    run_git(vault.path, "branch", "other", "main")
    run_git(vault.path, "checkout", "-q", "other")
    with pytest.raises(VaultError, match="not '%s'" % vault.branch):
        vaultmod.ensure_writable(config_for(vault))


def test_refuses_to_write_on_main(vault):
    run_git(vault.path, "checkout", "-q", "main")
    with pytest.raises(VaultError, match="refusing to write on 'main'"):
        vaultmod.ensure_writable(config_for(vault, "main"))


def test_dirty_work_tree(vault):
    (vault.path / "dirty.md").write_text("x\n", encoding="utf-8")
    with pytest.raises(VaultError, match="not clean"):
        vaultmod.ensure_writable(config_for(vault))


def test_branch_behind_main(vault):
    """main must be an ancestor of the working branch before any allocation."""
    run_git(vault.path, "checkout", "-q", "main")
    run_git(vault.path, "commit", "-q", "--allow-empty", "-m", "later work on main")
    run_git(vault.path, "checkout", "-q", vault.branch)
    with pytest.raises(VaultError, match="does not contain 'main'"):
        vaultmod.ensure_writable(config_for(vault))


def test_a_clean_up_to_date_branch_passes(vault):
    vaultmod.ensure_writable(config_for(vault))


# --- safe_path: precondition 7 ----------------------------------------------


def test_safe_path_refuses_a_symlinked_component(vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault.path / "hunt").symlink_to(outside, target_is_directory=True)
    with pytest.raises(VaultError, match="symlink"):
        vaultmod.safe_path(vault.path, "hunt", "HNT-001", "HNT-001.md")


def test_safe_path_refuses_an_escape(vault):
    with pytest.raises(VaultError, match="escape"):
        vaultmod.safe_path(vault.path, "..", "elsewhere.md")


def test_safe_path_refuses_an_absolute_component(vault):
    with pytest.raises(VaultError, match="relative"):
        vaultmod.safe_path(vault.path, "/etc/passwd")


def test_safe_path_returns_the_target(vault):
    target = vaultmod.safe_path(vault.path, "hunt", "HNT-001", "HNT-001.md")
    assert target == vault.path / "hunt" / "HNT-001" / "HNT-001.md"


# --- init --------------------------------------------------------------------


def test_init_creates_repo_main_and_branch(tmp_path):
    root = tmp_path / "fresh"
    vaultmod.init(root, "drafting")
    assert vaultmod.is_repo(root)
    assert vaultmod.current_branch(root) == "drafting"
    assert vaultmod.contains_main(root, "drafting")


def test_init_is_idempotent_and_keeps_history(tmp_path):
    root = tmp_path / "fresh"
    vaultmod.init(root, "drafting")
    before = run_git(root, "rev-parse", "HEAD").strip()
    log_before = run_git(root, "log", "--format=%H")
    vaultmod.init(root, "drafting")
    assert run_git(root, "rev-parse", "HEAD").strip() == before
    assert run_git(root, "log", "--format=%H") == log_before


def test_init_writes_the_optional_git_settings_into_the_local_config(
    tmp_path, monkeypatch
):
    # The fixture identity comes through the environment and would win over
    # any config; without it the root commit must be signed by what hunt.conf
    # configured, which is the point of applying the settings before it.
    for key in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(key)
    root = tmp_path / "fresh"
    configured = []
    vaultmod.init(
        root,
        "drafting",
        remote="git@github.com:example/vault.git",
        user_name="Ada Lovelace",
        user_email="ada@example.com",
        configured=configured,
    )
    assert configured == [
        "push.autoSetupRemote=true",
        "user.name=Ada Lovelace",
        "user.email=ada@example.com",
        "remote.origin.url=git@github.com:example/vault.git",
    ]
    assert run_git(root, "config", "--local", "user.name").strip() == "Ada Lovelace"
    assert run_git(root, "config", "--local", "user.email").strip() == "ada@example.com"
    assert (
        run_git(root, "config", "--local", "remote.origin.url").strip()
        == "git@github.com:example/vault.git"
    )
    assert (
        run_git(root, "log", "-1", "--format=%an <%ae>", "main").strip()
        == "Ada Lovelace <ada@example.com>"
    )
    # The global config is a test-owned file (conftest), and it stays untouched.
    global_config = Path(os.environ["GIT_CONFIG_GLOBAL"])
    assert (
        not global_config.exists() or "ada@example.com" not in global_config.read_text()
    )


def test_init_without_the_optional_settings_leaves_the_local_config_alone(tmp_path):
    root = tmp_path / "fresh"
    configured = []
    vaultmod.init(root, "drafting", configured=configured)
    # Only the unconditional push setting, which needs no hunt.conf value.
    assert configured == ["push.autoSetupRemote=true"]
    local = run_git(root, "config", "--local", "--list")
    assert "user.name" not in local
    assert "user.email" not in local
    assert "remote.origin" not in local


def test_init_always_sets_push_auto_setup_remote_in_the_local_config(tmp_path):
    root = tmp_path / "fresh"
    configured = []
    vaultmod.init(root, "drafting", configured=configured)
    assert run_git(root, "config", "--local", "push.autoSetupRemote").strip() == "true"
    assert "push.autoSetupRemote=true" in configured
    # The global config is a test-owned file (conftest), and it stays untouched.
    global_config = Path(os.environ["GIT_CONFIG_GLOBAL"])
    assert (
        not global_config.exists()
        or "autoSetupRemote" not in global_config.read_text()
    )
    # Already set: a repeated init has nothing to change and says nothing.
    again = []
    vaultmod.init(root, "drafting", configured=again)
    assert again == []


def test_init_reapplies_only_settings_that_changed(tmp_path):
    root = tmp_path / "fresh"
    vaultmod.init(
        root, "drafting", remote="https://example.com/old.git", user_name="Ada"
    )
    configured = []
    vaultmod.init(
        root,
        "drafting",
        remote="https://example.com/new.git",
        user_name="Ada",
        user_email="ada@example.com",
        configured=configured,
    )
    assert configured == [
        "user.email=ada@example.com",
        "remote.origin.url=https://example.com/new.git",
    ]
    assert (
        run_git(root, "config", "--local", "remote.origin.url").strip()
        == "https://example.com/new.git"
    )
    assert run_git(root, "remote").split() == ["origin"]
    configured = []
    vaultmod.init(
        root,
        "drafting",
        remote="https://example.com/new.git",
        user_name="Ada",
        user_email="ada@example.com",
        configured=configured,
    )
    assert configured == []


def test_init_refuses_to_nest_inside_an_enclosing_repository(vault):
    """vault-spec 5: initialization must not create a repository inside another."""
    nested = vault.path / "nested"
    nested.mkdir()
    with pytest.raises(VaultError, match="inside"):
        vaultmod.init(nested, "drafting")
    assert not (nested / ".git").exists()


# --- commit ------------------------------------------------------------------


def test_commit_stages_only_the_given_paths(vault):
    wanted = vault.path / "wanted.md"
    wanted.write_text("keep\n", encoding="utf-8")
    unrelated = vault.path / "unrelated.md"
    unrelated.write_text("leave me\n", encoding="utf-8")

    vaultmod.commit(vault.path, [wanted], "hunt: test", vault.branch)

    committed = run_git(vault.path, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["wanted.md"]
    assert "unrelated.md" in run_git(vault.path, "status", "--porcelain")


def test_commit_requires_at_least_one_path(vault):
    with pytest.raises(VaultError, match="at least one path"):
        vaultmod.commit(vault.path, [], "hunt: empty", vault.branch)


def test_commit_refuses_a_path_outside_the_vault(vault, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("no\n", encoding="utf-8")
    with pytest.raises(VaultError, match="outside the vault"):
        vaultmod.commit(vault.path, [outside], "hunt: escape", vault.branch)


def test_commit_refuses_a_relative_path_that_escapes(vault):
    with pytest.raises(VaultError, match="outside the vault"):
        vaultmod.commit(vault.path, ["../escape.md"], "hunt: escape", vault.branch)


# --- commit: the branch is checked again at the commit itself (vault-spec 4) --


def test_commit_refuses_when_main_is_the_branch(vault):
    run_git(vault.path, "checkout", "-q", "main")
    target = vault.path / "card.md"
    target.write_text("x\n", encoding="utf-8")
    with pytest.raises(VaultError, match="refusing to commit on 'main'"):
        vaultmod.commit(vault.path, [target], "hunt: test", "main")
    assert run_git(vault.path, "log", "--format=%s").splitlines() == ["root"]
    assert "card.md" not in run_git(vault.path, "diff", "--cached", "--name-only")


def test_commit_refuses_when_head_is_not_the_given_branch(vault):
    run_git(vault.path, "checkout", "-q", "main")
    target = vault.path / "card.md"
    target.write_text("x\n", encoding="utf-8")
    with pytest.raises(VaultError, match="on branch 'main', not '%s'" % vault.branch):
        vaultmod.commit(vault.path, [target], "hunt: test", vault.branch)
    assert run_git(vault.path, "log", "--format=%s").splitlines() == ["root"]
    assert run_git(vault.path, "diff", "--cached", "--name-only") == ""


def test_commit_refuses_a_detached_head(vault):
    run_git(vault.path, "checkout", "-q", "--detach")
    target = vault.path / "card.md"
    target.write_text("x\n", encoding="utf-8")
    with pytest.raises(VaultError, match="detached HEAD"):
        vaultmod.commit(vault.path, [target], "hunt: test", vault.branch)
    assert run_git(vault.path, "log", "--format=%s").splitlines() == ["root"]


# --- tracked_blobs -----------------------------------------------------------


def test_tracked_blobs_reads_every_blob_with_one_batch_process(vault, monkeypatch):
    first = vault.path / "first.txt"
    first.write_bytes(b"first\x00blob\n")
    second = vault.path / "nested" / "second.txt"
    second.parent.mkdir()
    second.write_bytes(b"second blob\n")
    run_git(vault.path, "add", "--", "first.txt", "nested/second.txt")
    run_git(vault.path, "commit", "-q", "-m", "two blobs")

    real_run = vaultmod.subprocess.run
    commands = []

    def recording_run(command, *args, **kwargs):
        if command[:3] == ["git", "-C", str(vault.path)]:
            commands.append(command[3:])
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(vaultmod.subprocess, "run", recording_run)

    blobs = vaultmod.tracked_blobs(vault.path)

    assert blobs == [
        (".gitattributes", b"* text=auto eol=lf\n"),
        ("first.txt", b"first\x00blob\n"),
        ("nested/second.txt", b"second blob\n"),
    ]
    assert len(commands) == 2
    assert commands[0][:3] == ["ls-tree", "-r", "-z"]
    assert commands[1] == ["cat-file", "--batch"]
