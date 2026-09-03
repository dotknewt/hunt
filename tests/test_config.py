from pathlib import Path

import pytest

from hunt import HuntError
from hunt.config import ConfigUnset, load_config, require_configured, write_config

from conftest import write_file

GOOD = 'VAULT_PATH="/srv/vault"\nVAULT_BRANCH="drafting"\n'


def conf_at(directory, text):
    return write_file(directory / "hunt.conf", text)


def test_parses_the_conf_written_by_the_vault_fixture(vault, monkeypatch):
    monkeypatch.chdir(vault.conf.parent)
    config = load_config()
    assert config.vault_path == vault.path
    assert config.vault_path.is_absolute()
    assert config.vault_branch == vault.branch


def test_comments_and_blank_lines_are_ignored(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    conf_at(
        root,
        "# where the cards live\n"
        "\n"
        'VAULT_PATH="/srv/vault"\n'
        "\n"
        "# which branch to draft on\n"
        'VAULT_BRANCH="drafting"\n',
    )
    monkeypatch.chdir(root)
    config = load_config()
    assert config.vault_path == Path("/srv/vault")
    assert config.vault_branch == "drafting"


def test_a_value_may_contain_spaces(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    conf_at(root, 'VAULT_PATH="/srv/my cards"\nVAULT_BRANCH="knut-hagane"\n')
    monkeypatch.chdir(root)
    config = load_config()
    assert config.vault_path == Path("/srv/my cards")
    assert config.vault_branch == "knut-hagane"


def test_a_branch_name_with_a_space_is_rejected(tmp_path, monkeypatch):
    """vault-spec 1.2: VAULT_BRANCH must be a name git check-ref-format accepts,
    and git rejects a space."""
    root = tmp_path.resolve()
    conf_at(root, 'VAULT_PATH="/srv/vault"\nVAULT_BRANCH="knut hagane"\n')
    monkeypatch.chdir(root)
    with pytest.raises(HuntError, match="VAULT_BRANCH"):
        load_config()


def test_hunt_conf_env_overrides_walk_up(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    near = root / "near"
    near.mkdir()
    conf_at(near, 'VAULT_PATH="/srv/near"\nVAULT_BRANCH="near"\n')
    elsewhere = root / "elsewhere"
    elsewhere.mkdir()
    chosen = conf_at(elsewhere, 'VAULT_PATH="/srv/chosen"\nVAULT_BRANCH="chosen"\n')
    monkeypatch.chdir(near)
    monkeypatch.setenv("HUNT_CONF", str(chosen))
    config = load_config()
    assert config.vault_path == Path("/srv/chosen")
    assert config.vault_branch == "chosen"


def test_hunt_conf_env_naming_a_missing_file_is_an_error(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    conf_at(root, GOOD)
    monkeypatch.chdir(root)
    monkeypatch.setenv("HUNT_CONF", str(root / "absent.conf"))
    with pytest.raises(HuntError, match="absent.conf"):
        load_config()


def test_user_conf_is_used_when_nothing_else_is_found(tmp_path, monkeypatch):
    """vault-spec 2 step 2: ~/.config/hunt/hunt.conf serves a directory that has
    no hunt.conf of its own anywhere above it."""
    root = tmp_path.resolve()
    home = root / "home"
    conf_at(home / ".config" / "hunt", 'VAULT_PATH="/srv/user"\nVAULT_BRANCH="user"\n')
    elsewhere = root / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("HOME", str(home))
    config = load_config()
    assert config.vault_path == Path("/srv/user")
    assert config.vault_branch == "user"


def test_user_conf_outranks_the_walk_up(tmp_path, monkeypatch):
    """The per-user file is step 2 and the ascent is step 3, so a hunt.conf in
    the checkout does not shadow it."""
    root = tmp_path.resolve()
    home = root / "home"
    conf_at(home / ".config" / "hunt", 'VAULT_PATH="/srv/user"\nVAULT_BRANCH="user"\n')
    repo = root / "repo"
    conf_at(repo, 'VAULT_PATH="/srv/repo"\nVAULT_BRANCH="repo"\n')
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(home))
    assert load_config().vault_branch == "user"


def test_hunt_conf_env_outranks_the_user_conf(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    home = root / "home"
    conf_at(home / ".config" / "hunt", 'VAULT_PATH="/srv/user"\nVAULT_BRANCH="user"\n')
    chosen = conf_at(root / "elsewhere", 'VAULT_PATH="/srv/chosen"\nVAULT_BRANCH="chosen"\n')
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HUNT_CONF", str(chosen))
    assert load_config().vault_branch == "chosen"


def test_hunt_conf_env_at_a_missing_file_does_not_fall_back_to_the_user_conf(
    tmp_path, monkeypatch
):
    """vault-spec 2 step 1: an explicit pointer at a missing file is an error,
    never a request to look somewhere else."""
    root = tmp_path.resolve()
    home = root / "home"
    conf_at(home / ".config" / "hunt", 'VAULT_PATH="/srv/user"\nVAULT_BRANCH="user"\n')
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HUNT_CONF", str(root / "absent.conf"))
    with pytest.raises(HuntError, match="absent.conf"):
        load_config()


def test_a_user_conf_directory_is_not_a_config(tmp_path, monkeypatch):
    """Only a regular file answers; a stray directory at that path must not
    shadow the checkout's hunt.conf."""
    root = tmp_path.resolve()
    home = root / "home"
    (home / ".config" / "hunt" / "hunt.conf").mkdir(parents=True)
    repo = root / "repo"
    conf_at(repo, 'VAULT_PATH="/srv/repo"\nVAULT_BRANCH="repo"\n')
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(home))
    assert load_config().vault_branch == "repo"


def test_no_conf_anywhere_names_the_user_conf_it_looked_for(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    home = root / "home"
    home.mkdir()
    deep = root / "a" / "b"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    monkeypatch.setenv("HOME", str(home))
    with pytest.raises(HuntError, match=r"\.config/hunt/hunt\.conf"):
        load_config()


def test_walk_up_finds_an_ancestor_conf(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    conf_at(root, GOOD)
    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    assert load_config().vault_branch == "drafting"


def test_walk_up_takes_the_nearest_conf(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    conf_at(root, 'VAULT_PATH="/srv/far"\nVAULT_BRANCH="far"\n')
    a = root / "a"
    a.mkdir()
    conf_at(a, 'VAULT_PATH="/srv/near"\nVAULT_BRANCH="near"\n')
    deep = a / "b"
    deep.mkdir()
    monkeypatch.chdir(deep)
    config = load_config()
    assert config.vault_path == Path("/srv/near")
    assert config.vault_branch == "near"


def test_no_conf_anywhere_is_an_error(tmp_path, monkeypatch):
    deep = tmp_path.resolve() / "a" / "b"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    with pytest.raises(HuntError, match="hunt.conf"):
        load_config()


def test_unknown_key_is_an_error(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    conf_at(root, GOOD + 'VAULT_REMOTE="origin"\n')
    monkeypatch.chdir(root)
    with pytest.raises(HuntError, match="VAULT_REMOTE"):
        load_config()


def test_duplicate_key_is_an_error(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    conf_at(root, 'VAULT_PATH="/srv/one"\nVAULT_PATH="/srv/two"\nVAULT_BRANCH="drafting"\n')
    monkeypatch.chdir(root)
    with pytest.raises(HuntError, match="VAULT_PATH"):
        load_config()


@pytest.mark.parametrize(
    "text,missing",
    [
        ('VAULT_PATH="/srv/vault"\n', "VAULT_BRANCH"),
        ('VAULT_BRANCH="drafting"\n', "VAULT_PATH"),
        ("# nothing but a comment\n", "VAULT_PATH"),
    ],
)
def test_missing_key_is_an_error(tmp_path, monkeypatch, text, missing):
    root = tmp_path.resolve()
    conf_at(root, text)
    monkeypatch.chdir(root)
    with pytest.raises(HuntError, match=missing):
        load_config()


def test_tilde_in_vault_path_is_expanded(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    home = root / "home"
    home.mkdir()
    conf_at(root, 'VAULT_PATH="~/cards"\nVAULT_BRANCH="drafting"\n')
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("USERPROFILE", raising=False)
    config = load_config()
    assert config.vault_path == home / "cards"


def test_tilde_is_not_expanded_inside_vault_branch(tmp_path, monkeypatch):
    """The branch is never ~-expanded. It is now rejected outright, because git
    rejects '~' in a ref name (vault-spec 1.2); the error must name the branch,
    proving no expansion turned it into a path."""
    root = tmp_path.resolve()
    home = root / "home"
    home.mkdir()
    conf_at(root, 'VAULT_PATH="/srv/vault"\nVAULT_BRANCH="~/drafting"\n')
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(home))
    with pytest.raises(HuntError, match="VAULT_BRANCH"):
        load_config()


@pytest.mark.parametrize("value", ["cards", "./cards", "../cards", "vault/BSL-001"])
def test_relative_vault_path_is_rejected(tmp_path, monkeypatch, value):
    root = tmp_path.resolve()
    conf_at(root, 'VAULT_PATH="{}"\nVAULT_BRANCH="drafting"\n'.format(value))
    monkeypatch.chdir(root)
    with pytest.raises(HuntError, match="VAULT_PATH"):
        load_config()


@pytest.mark.parametrize(
    "line",
    [
        "VAULT_PATH /srv/vault",
        'VAULT_PATH="/srv/vault',
        "VAULT_PATH=/srv/vault",
        '"VAULT_PATH"="/srv/vault"',
        'VAULT_PATH="/srv/vault" trailing',
        'export VAULT_PATH="/srv/vault"',
        'VAULT PATH="/srv/vault"',
    ],
)
def test_malformed_line_is_an_error(tmp_path, monkeypatch, line):
    root = tmp_path.resolve()
    conf_at(root, line + '\nVAULT_BRANCH="drafting"\n')
    monkeypatch.chdir(root)
    with pytest.raises(HuntError):
        load_config()


# --- unconfigured is a state, not an error (vault-spec 1.2) ------------------


@pytest.mark.parametrize(
    "text,unset",
    [
        ('VAULT_PATH=""\nVAULT_BRANCH=""\n', ("VAULT_PATH", "VAULT_BRANCH")),
        ('VAULT_PATH=""\nVAULT_BRANCH="drafting"\n', ("VAULT_PATH",)),
        ('VAULT_PATH="/srv/vault"\nVAULT_BRANCH=""\n', ("VAULT_BRANCH",)),
    ],
)
def test_empty_value_parses_as_unset(tmp_path, monkeypatch, text, unset):
    root = tmp_path.resolve()
    conf_at(root, text)
    monkeypatch.chdir(root)
    config = load_config()
    assert config.unset == unset
    assert config.path == root / "hunt.conf"


def test_the_repo_conf_parses(monkeypatch):
    """The file this repository ships with must be readable, not an error."""
    repo_conf = Path(__file__).resolve().parent.parent / "hunt.conf"
    config = load_config(repo_conf)
    assert config.unset == ("VAULT_PATH", "VAULT_BRANCH")


def test_require_configured_names_the_file_and_every_unset_key(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    conf_at(root, 'VAULT_PATH=""\nVAULT_BRANCH=""\n')
    monkeypatch.chdir(root)
    with pytest.raises(ConfigUnset) as caught:
        require_configured(load_config())
    message = str(caught.value)
    assert "VAULT_PATH" in message
    assert "VAULT_BRANCH" in message
    assert str(root / "hunt.conf") in message


def test_require_configured_passes_a_full_config_through(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    conf_at(root, GOOD)
    monkeypatch.chdir(root)
    config = load_config()
    assert require_configured(config) is config


def test_lowercase_key_is_a_syntax_error(tmp_path, monkeypatch):
    """vault-spec 1.1 spells keys in upper case. Before the regex was tightened
    only the closed-key check rejected this, and it did so as an unknown key."""
    root = tmp_path.resolve()
    conf_at(root, 'vault_path="/srv/vault"\nVAULT_BRANCH="drafting"\n')
    monkeypatch.chdir(root)
    with pytest.raises(HuntError, match="expected"):
        load_config()


# --- write_config -----------------------------------------------------------


def test_write_config_round_trips(tmp_path):
    conf = conf_at(tmp_path, 'VAULT_PATH=""\nVAULT_BRANCH=""\n')
    write_config(conf, {"VAULT_PATH": "/srv/vault", "VAULT_BRANCH": "drafting"})
    config = load_config(conf)
    assert config.vault_path == Path("/srv/vault")
    assert config.vault_branch == "drafting"
    assert config.unset == ()


def test_write_config_preserves_comments_and_blank_lines(tmp_path):
    conf = conf_at(
        tmp_path,
        "# where my vault lives\nVAULT_PATH=\"\"\n\n# the branch I draft on\nVAULT_BRANCH=\"\"\n",
    )
    write_config(conf, {"VAULT_PATH": "/srv/vault", "VAULT_BRANCH": "drafting"})
    assert conf.read_text() == (
        "# where my vault lives\n"
        'VAULT_PATH="/srv/vault"\n'
        "\n"
        "# the branch I draft on\n"
        'VAULT_BRANCH="drafting"\n'
    )


def test_write_config_creates_a_file_that_does_not_exist(tmp_path):
    conf = tmp_path / "hunt.conf"
    write_config(conf, {"VAULT_PATH": "/srv/vault", "VAULT_BRANCH": "drafting"})
    assert conf.read_text() == 'VAULT_PATH="/srv/vault"\nVAULT_BRANCH="drafting"\n'


def test_write_config_emits_lf_and_a_trailing_newline(tmp_path):
    conf = tmp_path / "hunt.conf"
    write_config(conf, {"VAULT_PATH": "/srv/vault", "VAULT_BRANCH": "drafting"})
    data = conf.read_bytes()
    assert b"\r" not in data
    assert data.endswith(b"\n")
    assert data.decode("ascii")


def test_write_config_refuses_an_unknown_key(tmp_path):
    conf = conf_at(tmp_path, GOOD)
    with pytest.raises(HuntError, match="VAULT_REMOTE"):
        write_config(conf, {"VAULT_REMOTE": "origin"})
    assert conf.read_text() == GOOD


def test_write_config_refuses_a_value_holding_a_quote(tmp_path):
    conf = conf_at(tmp_path, GOOD)
    with pytest.raises(HuntError, match="VAULT_PATH"):
        write_config(conf, {"VAULT_PATH": '/srv/"odd"'})
    assert conf.read_text() == GOOD


def test_write_config_leaves_no_temporary_file_behind(tmp_path):
    conf = tmp_path / "hunt.conf"
    write_config(conf, {"VAULT_PATH": "/srv/vault", "VAULT_BRANCH": "drafting"})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["hunt.conf"]
