# hunt

`hunt` creates, extends and validates threat-hunting task cards in an Obsidian
vault that lives outside this repository.

Two documents are normative and this README is not:

- [`docs/card-spec.md`](docs/card-spec.md) — what a card file contains, and
  how a tree of them is shaped.
- [`docs/vault-spec.md`](docs/vault-spec.md) — where that tree lives, how it
  is configured, and how git is used.

## Install

```sh
uv tool install --from . hunt      # global `hunt` on PATH
uv tool install --editable .       # ...tracking the working tree instead
```

`uv tool install` resolves dependencies itself and **ignores `uv.lock`**. The
lockfile governs `uv sync` and `uv run` only, which is how the tests run:

```sh
uv sync --locked
uv run pytest
```

## Configure

`hunt` reads `hunt.conf` from the current directory or the nearest ancestor
that has one (`HUNT_CONF` overrides the search):

```
VAULT_PATH="/absolute/path/to/vault"
VAULT_BRANCH="drafting"
```

Both keys must be present. An **empty value means unconfigured**, which is a
state rather than an error: `hunt --help`, `hunt completion` and tab completion
all keep working, and a command that needs the value refuses with a message
naming the file and the missing keys. The `hunt.conf` tracked here carries empty
values and CI enforces that it still does — filling it in is a local edit that
must not reach `main`.

`VAULT_BRANCH` must not be `main`. `main` is the record; `hunt` never writes on
it after initialization.

## Use

```sh
hunt init --vault-path ~/vaults/hunting --vault-branch drafting
hunt new -c h                     # -> HNT-001, titled after its own id
hunt new -c hunt --name "Monthly encoded PowerShell persistence hunt"
hunt run --id HNT-001
hunt validate
```

`hunt init` writes any `hunt.conf` value given on the command line (prompting
before replacing one that is already set, or `--yes` to skip the prompt),
creates the vault and its `main` and working branches if they do not exist, and
writes the vault scaffold: `.gitattributes`, `.gitignore` and three minimal
`.obsidian` configs. It never overwrites a file that already exists, so running
it again on a configured vault verifies and succeeds without committing.

`-c` accepts any spelling of a category, case-insensitively:
`baseline`/`BSL`/`b`, `hunt`/`HNT`/`h`, `math`/`MTH`/`m`.

`hunt validate` exits 0 when the vault conforms and 1 with one finding per line
otherwise. It is read-only.

## Completion

```sh
hunt completion zsh > "${fpath[1]}/_hunt"     # then restart the shell
hunt completion bash > /etc/bash_completion.d/hunt
hunt completion powershell >> $PROFILE
```

Each script shells out to `hunt __complete {ids,categories}` for the values that
depend on the vault, so no shell script knows where the vault is or how a card
is named. Adding a shell means translating one call. `HUNT_COMPLETE_DEBUG=1`
surfaces errors a completer would otherwise swallow.

## Line endings

Cards are LF, always, and CRLF must never reach a remote branch — including on
Windows, where `core.autocrlf=true` is the git default. Four things enforce it:
`* text=auto eol=lf` in the vault's root commit, a refusal in `hunt`'s own
commit path when a staged blob carries CR, a `bytes.crlf-committed` finding
read from committed blobs rather than the work tree, and a
`path.missing-gitattributes` finding when the guarantee itself has been removed.

`hunt` never pushes. A vault remote should protect `main` with a branch rule
that runs `hunt validate` on every merge candidate.

## Environment artifacts

`.DS_Store` and `Thumbs.db` are never findings, wherever they appear. `init`,
`new` and `run` delete them before checking that the work tree is clean, and
report what they removed; `validate` only ignores them.
