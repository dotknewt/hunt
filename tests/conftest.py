import os
import subprocess

import pytest

BRANCH = "drafting"

GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "hunt tests",
    "GIT_AUTHOR_EMAIL": "tests@example.invalid",
    "GIT_COMMITTER_NAME": "hunt tests",
    "GIT_COMMITTER_EMAIL": "tests@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}


def run_git(repo, *args):
    env = dict(os.environ)
    env.update(GIT_ENV)
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            "git {} failed with {}:\n{}{}".format(
                " ".join(args), result.returncode, result.stdout, result.stderr
            )
        )
    return result.stdout


def write_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


class Vault:
    def __init__(self, path, conf, branch):
        self.path = path
        self.conf = conf
        self.branch = branch

    def git(self, *args):
        return run_git(self.path, *args)

    def write(self, relpath, text):
        return write_file(self.path / relpath, text)

    def log(self):
        out = self.git("log", "--format=%s")
        return out.splitlines()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path_factory):
    home = tmp_path_factory.mktemp("githome")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    for key in ("HUNT_CONF", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    path = root / "vault"
    path.mkdir()
    run_git(path, "init", "-q")
    run_git(path, "symbolic-ref", "HEAD", "refs/heads/main")
    run_git(path, "config", "user.name", "hunt tests")
    run_git(path, "config", "user.email", "tests@example.invalid")
    run_git(path, "config", "commit.gpgsign", "false")
    run_git(path, "config", "core.autocrlf", "false")
    run_git(path, "commit", "-q", "--allow-empty", "-m", "root")
    run_git(path, "checkout", "-q", "-b", BRANCH)
    conf = write_file(
        root / "hunt.conf",
        'VAULT_PATH="{}"\nVAULT_BRANCH="{}"\n'.format(path, BRANCH),
    )
    # Without this, load_config() walks up from the cwd and finds the developer's
    # real hunt.conf, pointing the tests at the live vault.
    monkeypatch.setenv("HUNT_CONF", str(conf))
    return Vault(path=path, conf=conf, branch=BRANCH)
