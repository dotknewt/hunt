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

`hunt` looks for `hunt.conf` in three places and takes the first that has one:
`$HUNT_CONF`, then `~/.config/hunt/hunt.conf`, then the current directory or the
nearest ancestor that has one. Configuring yourself once at
`~/.config/hunt/hunt.conf` covers every checkout, and keeps your values out of a
repository that tracks the file:

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
hunt new -c hunt --name "Monthly encoded PowerShell persistence hunt" --cadence 30
hunt run --id HNT-001
hunt run --id HNT-001 --scope "windows servers"
hunt validate
```

`hunt init` writes any `hunt.conf` value given on the command line (prompting
before replacing one that is already set, or `--yes` to skip the prompt),
creates the vault and its `main` and working branches if they do not exist, and
writes the vault scaffold: `.gitattributes`, `.gitignore`, a GitHub Actions
workflow at `.github/workflows/hunt.yml` and three minimal `.obsidian` configs.
It never overwrites a file that already exists, so running it again on a
configured vault verifies and succeeds without committing.

`-c` accepts any spelling of a category, case-insensitively:
`baseline`/`BSL`/`b`, `hunt`/`HNT`/`h`, `math`/`MTH`/`m`.

`hunt run --scope` records what the run covered - `windows`, `on-prem`,
`clients`, or any phrase that fits. It is optional and free text: `hunt` checks
that the value is a single line of printable ASCII and nothing more. There is
no list of permitted scopes, and nothing enforces one.

`hunt new --cadence` records how often, in days, the task is meant to recur.
It is optional and takes a positive integer; `hunt` checks only that the
value is well formed, not what it is. Unlike most parent-card fields, it can
be changed later, since it is a scheduling parameter rather than a record of
what happened.

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

`hunt` never pushes, and it never commits on `main`: `new` and `run` refuse
unless `VAULT_BRANCH` is checked out, and the commit path checks the branch
again immediately before `git commit`, so nothing that reaches `vault.commit`
can land on the record.

## Vault CI and branch protection

The scaffolded `.github/workflows/hunt.yml` runs two checks on every pull
request into the vault's `main` and on every push to it: `validate`, which
installs `hunt` from this repository and runs `hunt validate` against the
checkout (duplicate ids and filenames, numbering gaps, malformed cards, CR bytes
in any committed blob), and `line-endings`, an independent shell check for CR
bytes. The workflow pins the `hunt` revision it installs through `HUNT_REF`;
set it to a tag or commit once you want the vault's checks to stop tracking
`main` here.

Protect the vault's `main` on GitHub (Settings > Branches, or a ruleset):
require a pull request before merging, require the `validate` and
`line-endings` status checks, and block force pushes and deletion. With that
rule in place, work only ever reaches `main` through a reviewed merge that
passed validation, which is the binding `docs/vault-spec.md` Section 4 relies
on.

Transition validation (`docs/card-spec.md` Section 8.2: nothing accepted is
deleted, renumbered or reused across branches) is not implemented yet. The
workflow carries a placeholder step for it, and until `hunt validate --against`
exists the check is part of the human review of each merge.

## Environment artifacts

`.DS_Store` and `Thumbs.db` are never findings, wherever they appear. `init`,
`new` and `run` delete them before checking that the work tree is clean, and
report what they removed; `validate` only ignores them.
