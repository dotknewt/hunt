# Vault Location, Configuration, and Git Workflow

**Version:** 1
**Status:** normative configuration and workflow contract.
**Scope:** where the vault lives, how a tool finds it, what may exist inside
it, which branch is written, what MUST be true before any write, how each
mutation is committed, and how numbers are allocated. The card format itself
is specified in `docs/card-spec.md`; this document specifies what that
document deliberately leaves out. Command-line surface, exit codes, and test
strategy are not specified here.

Keywords **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, **MAY** are
normative (RFC 2119 sense).

Throughout, *the tool* means any program that reads or writes the vault under
this contract, and *a write* means creating, modifying, staging, or committing
a file in the vault.

---

## 1. `hunt.conf`

The vault's location and working branch are configuration, not spec. They live
in a file named exactly `hunt.conf`.

### 1.1 Format

The file is line oriented. Each line MUST be one of:

```
blank       := zero or more spaces
comment     := zero or more spaces, "#", then any characters
assignment  := KEY "=" '"' value '"'
KEY         := [A-Z][A-Z0-9_]*
```

- The file MUST be ASCII: every byte is LF (`0x0A`) or a printable ASCII byte
  in the range `0x20`-`0x7E`. It is UTF-8 with no byte-order mark.
- Line endings MUST be LF. A CR byte anywhere in the file is a violation.
- The file SHOULD end with a newline. A parser MUST accept a final line that
  has none; this is the one place these conventions are looser than a card
  file's (`docs/card-spec.md` Section 3.1), because `hunt.conf` is not a card
  and is never rendered.
- An assignment MUST have no space around the `=`, and MUST have nothing after
  the closing quote but the line ending.
- The value MUST be enclosed in double quotes. It MUST NOT contain a double
  quote, a backslash, or a newline.
- **The file is not shell.** Its syntax is deliberately shell-like so a human
  reading it is not surprised, but it MUST NOT be sourced or otherwise
  evaluated. No variable interpolation, no command substitution, no escape
  sequences, no line continuation, no `export`. The bytes between the quotes
  are the value, literally, with the single exception of `~` expansion in
  Section 1.2.
- A key MUST NOT appear more than once. A repeated key is an error, not
  last-wins.
- Any line that is not blank, a comment, or a well-formed assignment is an
  error. The tool MUST NOT skip lines it does not understand.

### 1.2 Schema

The schema is **closed**, exactly as the card frontmatter schema is closed
(`docs/card-spec.md` Section 4): a key that is not listed below is a
validation failure, not a value silently ignored. Both keys are REQUIRED;
either one missing is an error. An empty value (`KEY=""`) is an error.

| Key | Value |
|---|---|
| `VAULT_PATH` | absolute filesystem path to the vault root |
| `VAULT_BRANCH` | name of the Git branch the tool writes on |

`VAULT_PATH`:

- A leading `~/`, or a value of exactly `~`, MUST be expanded to the invoking
  user's home directory. No other expansion is performed: `$HOME`, `${HOME}`,
  `~other`, and a relative path are all errors rather than things to guess at.
- After expansion the value MUST be absolute and MUST NOT contain a `.` or
  `..` component.
- A trailing `/` is ignored; the path with and without it name the same vault.
- The path need not exist for the file to parse. Existence is a precondition
  (Section 5), not a syntax rule.

`VAULT_BRANCH`:

- MUST be non-empty and MUST be a valid Git branch name (`git check-ref-format
  --branch` accepts it).
- MUST NOT begin with `-`.
- MUST NOT be `main`. `main` is the record (`docs/card-spec.md` Section 1) and
  is never written by the tool (Section 4). Rejecting it here rather than at
  write time means the refusal cannot be bypassed by a later check being
  skipped.

Example:

```
# The vault is a separate repository from the tool.
VAULT_PATH="/Users/example/Code/task-vault"
VAULT_BRANCH="knut-hagane-lunden"
```

---

## 2. Resolution

The tool MUST locate `hunt.conf` by the following order, and MUST stop at the
first step that yields a candidate:

1. **`HUNT_CONF`.** If the environment variable `HUNT_CONF` is set and
   non-empty, its value is the path to the configuration file. A relative
   value is resolved against `$PWD`. This step does not walk up. If the named
   file does not exist, is not a regular file, or is not readable, that is an
   error; the tool MUST NOT fall through to step 2.
2. **Nearest `hunt.conf`.** Otherwise, starting at `$PWD` and ascending one
   directory at a time to the filesystem root, the first directory containing
   a readable regular file named `hunt.conf` provides it. The ascent is not
   stopped by a repository boundary, a mount point, or a home directory.
3. **Error.** Otherwise the tool MUST report that no configuration was found,
   and MUST NOT write anything.

There is **no user-global fallback**. `~/.hunt.conf`, `~/.config/hunt/`,
`/etc/hunt.conf`, and any other well-known location MUST NOT be consulted.
Configuration is per-checkout and explicit; a tool invoked from an unexpected
directory MUST fail rather than silently operate on some other vault.

The directory containing `hunt.conf` carries no meaning beyond having been
found: `VAULT_PATH` is absolute, so nothing is resolved relative to it.

Configuration is read once per invocation. A change to the file or to
`HUNT_CONF` during a run MUST NOT be observed part-way through.

---

## 3. The Vault Root

`VAULT_PATH` **is** the card root of `docs/card-spec.md` Section 3. The
`task-cards/` prefix shown in that document's layout diagrams stands for this
path; no rule depends on its absolute value or on its final directory name.

- The direct children of the vault root are the category directories of
  `docs/card-spec.md` Section 2.1 (`baseline`, `hunt`, `math`), plus
  `.obsidian/` and `.git/`. Nothing else MAY appear there.
- `.obsidian/` is Obsidian's own state and is the only permitted non-card
  entry whose contents this contract does not constrain. `.git/` is Git's own
  state. Both are exempt from the card-spec file rules; everything else under
  the vault root is not.
- The vault root is simultaneously the Obsidian vault root and the card root.
  There are no external notes and no attachments (`docs/card-spec.md`
  Section 1), so every link the card spec constrains is a link between card
  files.
- A category directory is created on demand, when the first parent in that
  category is created. An absent category directory is equivalent to an empty
  one; both yield `001` as the next parent number (Section 7).
- The vault root MUST be a directory, not a symlink to one.
- The vault MUST be a different repository from the tool's own repository, and
  MUST NOT be nested inside it. This follows from the rules above rather than
  standing alone: a tool checkout contains source, documentation, and
  `hunt.conf` itself, none of which may exist under the vault root.

---

## 4. Branch Model

- The vault is its own Git repository, independent of the tool's repository,
  with its own history and its own remotes.
- **`main` is the record** (`docs/card-spec.md` Section 1). Every immutability
  and numbering rule in the card spec is a statement about `main`.
- The tool writes only on `VAULT_BRANCH`, with exactly one exception:
  initialization (Section 5) creates `main` and its empty root commit before
  `VAULT_BRANCH` exists, so that commit necessarily lands on `main`. It writes
  no card. After initialization the tool never commits on `main` again.
- If `HEAD` is not `VAULT_BRANCH` the tool MUST refuse to write, whether
  `HEAD` is `main`, another branch, or detached.
  Because `VAULT_BRANCH` cannot be `main` (Section 1.2), the refusal to write
  on `main` is unconditional and cannot be configured away.
- Only initialization MAY check out a branch. Once the vault is initialized,
  the tool MUST NOT check out, create, delete, rename, merge, rebase, fetch,
  pull, or push any branch. Switching branches is the human's act.
- Getting work from `VAULT_BRANCH` onto `main` is out of scope for the tool:
  it is a human-reviewed merge, subject to main-transition validation
  (`docs/card-spec.md` Section 8.2).
- The tool MUST NOT rewrite history: no amend, no reset, no rebase, no forced
  update of any ref, no `filter-branch` equivalent.
- The tool MUST NOT stash, and MUST NOT modify any file outside the vault
  root.

---

## 5. Preconditions

Before a mutating command creates, modifies, or stages anything, all of the
following MUST hold. They are checked in this order, before any write, so that
the reported failure is the first one encountered and the vault is untouched
when a command refuses.

1. **Configuration is valid.** A `hunt.conf` was resolved (Section 2) and
   parses against the closed schema (Section 1).
2. **The vault exists.** `VAULT_PATH`, after `~` expansion, names an existing
   directory.
3. **The vault is a Git work tree, at its top level.** The vault root is the
   top level of a non-bare Git work tree; that is, the repository's top level
   resolves to the same directory as `VAULT_PATH`. A directory that merely
   sits inside some other repository is not a vault, and MUST be refused
   rather than written to.
4. **`VAULT_BRANCH` exists and is checked out.** It exists as a local branch
   and `HEAD` points at it symbolically. A detached `HEAD` at the same commit
   does not satisfy this.
5. **The work tree is clean.** Under the vault root there are no staged
   changes, no unstaged modifications, and no untracked files that Git does
   not ignore. A dirty tree is refused because a commit stages only the paths
   the command wrote (Section 6): with unrelated edits present, neither the
   author nor a reviewer can tell what a commit means, and a stray untracked
   Markdown file is a Section 3 violation waiting to be committed.
6. **`main` is an ancestor of `VAULT_BRANCH`.** A local branch `main` MUST
   exist and its tip MUST be an ancestor of the tip of `VAULT_BRANCH`; a
   branch sitting exactly at `main` satisfies this. This is the allocation
   precondition of `docs/card-spec.md` Section 2.2, and it is what makes
   allocation a directory scan (Section 7): it guarantees that every number
   ever assigned on `main` is present in the working tree. When it fails the
   tool MUST refuse, MUST NOT allocate, and MUST tell the user to merge or
   rebase `main` into `VAULT_BRANCH` first.
7. **No symlinked path component.** From the vault root down to and including
   each file the command will write, no path component is a symbolic link, and
   each target path, fully resolved, is still under the fully resolved vault
   root. This keeps a write from escaping the vault and keeps Git from
   recording something other than what was written.

**Read-only commands.** A command that only reads, such as validation, MUST
require preconditions 1 through 3 and MUST NOT require 4 through 7. Its job
includes reporting on work in progress, so refusing a dirty tree, a branch
behind `main`, or an unexpected `HEAD` would defeat it.

**Initialization.** A command whose purpose is to establish preconditions 3,
4, and 6 necessarily cannot require them. It MUST require 1, 2, and 7, and it
MUST be idempotent: on an already-initialized vault it verifies and succeeds
without writing. It MUST NOT rewrite or discard existing history, and MUST
NOT convert a directory that is already inside another repository into a
vault.

---

## 6. Commits

- **One commit per mutation.** A successful mutating command produces exactly
  one commit on `VAULT_BRANCH`. A command that writes nothing commits nothing.
- **Staging is explicit.** Only the paths the command itself wrote are staged.
  Blanket staging (`git add -A`, `git add .`, `git commit -a`) is forbidden.
  Together with precondition 5, this makes each commit's diff exactly the
  command's effect.
- **A mutation is committed whole.** When a command writes more than one file,
  all of them go into the single commit. In particular, a new run file and the
  parent card re-rendered from it (`docs/card-spec.md` Section 5.2) are
  committed together, so no commit on the branch shows a parent whose managed
  region disagrees with its run files.
- **Message format.** The message is a single ASCII line with no body, no
  trailing period, and no trailing whitespace:

  ```
  hunt: <command> <ID>
  ```

  Concretely, `hunt: new HNT-002` for a new parent and
  `hunt: run HNT-002.001` for a new run. `<ID>` is the bare identifier of the
  card the command created, in the grammar of `docs/card-spec.md` Section 2.1.
  An initialization commit, which creates no card, is `hunt: init`.
- **Identity is the repository's.** The commit uses the vault repository's
  configured author and committer. The tool MUST NOT override them and MUST
  NOT add trailers, sign-offs, or co-author lines.
- **No publishing.** The tool MUST NOT push, and MUST NOT create or modify a
  tag.
- **Failure leaves no partial commit.** If a write or the commit itself fails,
  the tool MUST NOT commit part of the mutation, and MUST report the paths it
  had already written. Recovery is straightforward precisely because the tree
  was clean beforehand: the written paths are the only difference from `HEAD`.

---

## 7. Allocation

Allocation follows `docs/card-spec.md` Section 2.2 and adds nothing to it. It
is restated here only in operational terms.

- The next parent number for a category is one greater than the greatest
  parent number present in that category directory in the working tree; the
  next run number for a parent is one greater than the greatest run number
  present in that parent directory. An absent or empty directory yields `001`.
- **The working tree is the only source.** No Git query is made: not
  `ls-tree`, not the index, not `main`. Precondition 6 is what licenses this,
  and it is why that precondition is not optional. A card created earlier on
  the same branch and not yet merged is present in the tree and therefore
  counts, so two successive creations in one category allocate `N` and `N+1`
  rather than colliding.
- Run numbers come from run filenames (`docs/card-spec.md` Section 4); nothing
  is read from frontmatter to allocate.
- **Gaps are never filled.** If a scan finds the present numbers are not
  exactly `1..N`, the tree already violates invariant 2 of
  `docs/card-spec.md` Section 7. The tool MUST refuse to allocate and MUST
  direct the user to validation, rather than allocating into the gap or past
  it.
- The scan treats names case-insensitively (`docs/card-spec.md` Section 2.1).
  Two entries in one directory whose names differ only in case are a
  violation; the tool MUST refuse to allocate rather than pick one.
- A request that would allocate number 1000 MUST be reported as an explicit
  error. It MUST NOT wrap, widen the padding, or reuse a number.
- **Cross-branch collisions are out of scope.** Precondition 6 removes the
  common case, a branch allocating while behind `main`. Two branches drafted
  in parallel from the same `main` can still allocate the same number;
  detecting and resolving that is a merge-time concern
  (`docs/card-spec.md` Section 8.2), not a function of this contract.
