from pathlib import Path

import pytest

from hunt import HuntError
from hunt.config import load_config

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


@pytest.mark.parametrize("value", ["cards", "./cards", "../cards", "vault/BSL-001", ""])
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
