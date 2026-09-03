# Vault Location, Configuration, and Git Workflow

**Version:** 2
**Status:** normative configuration and workflow contract.
**Scope:** where the vault lives, how a tool finds it, what may exist inside
it, which branch is written, what MUST be true before any write, how each
mutation is committed, how numbers are allocated, and how line endings are held
to LF. The card format itself is specified in `docs/card-spec.md`, which names
nothing outside the card tree; this document specifies everything around it and
is the only one of the two that mentions Git, configuration, or the editor.
Command-line surface, exit codes, and test strategy are not specified here.
**Changelog:** v2 absorbs the rules that `docs/card-spec.md` v3 stated about the
vault root's non-card contents, the configuration file, the editor's state
directory, and Git. A pre-existing contradiction between the two documents over
which files may sit at the vault root is resolved in the process, in favour of
the card spec's more permissive reading: `.gitignore` and `.gitattributes` join
the root inventory (Section 3). Section 8, holding line endings to LF, is new.
An empty configuration value now means *unconfigured* rather than being an error
(Section 1.2). The root commit MAY carry the scaffold that Section 5 now
defines, and Section 4 binds `main` to the card spec's *accepted tree*.

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
  has none. This is the one deliberate looseness in the format: `hunt.conf` is
  never rendered and never byte-compared, so a missing final newline costs
  nothing, whereas refusing to read a file over it would be gratuitous.
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

The schema is **closed**: a key that is not listed below is a validation
failure, not a value silently ignored. Both keys are REQUIRED to be *present*;
either one missing is an error.

| Key | Value |
|---|---|
| `VAULT_PATH` | absolute filesystem path to the vault root |
| `VAULT_BRANCH` | name of the Git branch the tool writes on |

**An empty value (`KEY=""`) means the key is unconfigured.** It is not an error
and MUST NOT be reported as one. A `hunt.conf` whose values are both empty is
the well-formed initial state of the file, which is what lets the file be
distributed, and version-controlled, by a tool checkout that has no vault.

- A command that needs an unconfigured value MUST refuse, MUST NOT write
  anything, and MUST name both the resolved path of the file and every key it
  needed that is unset, so that the remedy is unambiguous. Refusing over
  configuration is a different failure from refusing over the vault's state, and
  the two SHOULD be distinguishable to a caller.
- A command that needs neither value - printing usage, emitting a shell
  completion script, computing a completion candidate - MUST succeed with the
  file in that state.
- The rules below constrain a **configured** value, that is, a non-empty one.
  Being unconfigured is a property of the empty string alone; a value that is
  present and non-empty is validated in full.

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

- MUST be a valid Git branch name (`git check-ref-format --branch` accepts it).
- MUST NOT begin with `-`.
- MUST NOT be `main`. `main` is the record (Section 4) and is never written by
  the tool. Rejecting it here rather than at write time means the refusal cannot
  be bypassed by a later check being skipped.

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

`VAULT_PATH` **is** the card root of `docs/card-spec.md`, and the tree beneath
it MUST conform to that document. The `task-cards/` prefix shown in that
document's layout diagrams stands for this path; no rule depends on its absolute
value or on its final directory name. That is the whole of the seam between the
two contracts: the card spec says what a card is and how a tree of cards is
shaped, and this document says where that tree lives, what else lives beside it,
and how it is version-controlled.

The vault root is simultaneously the Obsidian vault root and the card root.
There are no external notes and no attachments, so every link inside a card is a
link to another card.

The direct children of the vault root are exactly:

| Entry | What it is |
|---|---|
| the category directories | the card tree; contents governed by the card spec |
| `.git/` | Git's own state |
| `.obsidian/` | Obsidian's own state |
| `.gitignore` | see below |
| `.gitattributes` | see below |

Nothing else MAY appear there: no attachment, no template, no tooling asset, and
no Markdown file outside a parent directory.

- `.git/` and `.obsidian/` are the two entries whose contents this contract does
  not constrain. Both are exempt from the card spec's file rules; everything
  else under the vault root is not.
- `.gitignore` is permitted, and SHOULD exist, because the clean-work-tree
  precondition (Section 5) is otherwise unsatisfiable on a filesystem that
  writes stray metadata into every directory, and because `.obsidian/` holds
  volatile files - window layout, caches, downloaded plugins - that are not part
  of the record. It MUST NOT ignore a card file.
- `.gitattributes` is permitted, and MUST exist, because it is what holds the
  card spec's line-ending rule in force against a Git client configured to
  translate line endings (Section 8). It MUST NOT exempt a card file from that
  rule.
- **Environment artifacts.** `.DS_Store` and `Thumbs.db` are the closed set of
  environment artifacts this contract exempts, under the provision for them in
  `docs/card-spec.md` Section 3, wherever in the tree they appear. They are
  written by the operating system rather than by an author, no author can
  prevent them, and a vault is not malformed for holding one: validation MUST
  NOT report them, at the root or at any depth. The tool MAY delete them, and a
  mutating command SHOULD delete them before checking the clean-work-tree
  precondition, which they would otherwise fail in a vault whose `.gitignore`
  has been removed. No other name is exempt and this set is not extensible at
  runtime.
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
- **`main` is the record.** `main`'s tree is the *accepted tree* of
  `docs/card-spec.md` Section 1; the tree of any other branch is a *proposed
  tree*. This is the binding that makes the card spec's immutability and
  numbering rules statements about `main` in this vault, that makes its
  transition validation (Section 8.2 of that document) a check on a merge
  candidate against the `main` it would replace, and that makes its allocation
  precondition precondition 6 below.
- The tool writes only on `VAULT_BRANCH`, with exactly one exception:
  initialization (Section 5) creates `main` and its root commit before
  `VAULT_BRANCH` exists, so that commit necessarily lands on `main`. That commit
  MAY carry the vault scaffold (Section 5), and MUST when initialization is what
  creates the repository, so that `.gitattributes` is in force on every branch
  ever forked from `main` and before any card is committed anywhere (Section 8).
  It writes no card. After initialization the tool never commits on `main`
  again.
- If `HEAD` is not `VAULT_BRANCH` the tool MUST refuse to write, whether
  `HEAD` is `main`, another branch, or detached.
  Because `VAULT_BRANCH` cannot be `main` (Section 1.2), the refusal to write
  on `main` is unconditional and cannot be configured away.
- Only initialization MAY check out a branch. Once the vault is initialized,
  the tool MUST NOT check out, create, delete, rename, merge, rebase, fetch,
  pull, or push any branch. Switching branches is the human's act.
- Getting work from `VAULT_BRANCH` onto `main` is out of scope for the tool:
  it is a human-reviewed merge, subject to transition validation.
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

1. **Configuration is valid.** A `hunt.conf` was resolved (Section 2), parses
   against the closed schema (Section 1), and every key the command needs is
   configured rather than empty (Section 1.2).
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
   branch sitting exactly at `main` satisfies this. It is what makes allocation
   a directory scan (Section 7): it guarantees that every number ever assigned
   on `main` is present in the working tree. When it fails the tool MUST refuse,
   MUST NOT allocate, and MUST tell the user to merge or rebase `main` into
   `VAULT_BRANCH` first.
7. **No symlinked path component.** From the vault root down to and including
   each file the command will write, no path component is a symbolic link, and
   each target path, fully resolved, is still under the fully resolved vault
   root. This keeps a write from escaping the vault and keeps Git from
   recording something other than what was written.

**Read-only commands.** A command that only reads, such as validation, MUST
require preconditions 1 through 3 and MUST NOT require 4 through 7. Its job
includes reporting on work in progress, so refusing a dirty tree, a branch
behind `main`, or an unexpected `HEAD` would defeat it.

**Initialization.** A command whose purpose is to establish preconditions 3, 4,
and 6 necessarily cannot require them. It MUST require 1, 2, and 7. It MUST NOT
rewrite or discard existing history, and MUST NOT convert a directory that is
already inside another repository into a vault.

Initialization is also the one command that MAY *write* the configuration, so it
MAY be given the values precondition 1 requires rather than reading them: a
value supplied on the command line satisfies that precondition for this run and
is recorded in the resolved `hunt.conf`. Replacing a value that is already
configured MUST require the user's confirmation; supplying only one of the two
MUST be refused before anything is written, since the command would otherwise
succeed and leave the vault unreachable.

Its postcondition is that preconditions 3, 4, and 6 hold and that the **vault
scaffold** exists and is committed. The scaffold is exactly these files:

| Path | Why initialization writes it |
|---|---|
| `.gitattributes` | holds the line-ending rule in force (Section 8) |
| `.gitignore` | makes the work tree cleanable (Section 3) |
| `.obsidian/app.json` | editor settings that keep an edited card conformant |
| `.obsidian/core-plugins.json` | the editor's enabled core plugins |
| `.obsidian/types.json` | the editor's frontmatter property types |

Only the first two are normative in their contents, as Section 3 states. The
three `.obsidian/` files are Obsidian's own state, so this contract does not
constrain what they say; initialization writes them because an unconfigured
editor rewrites card frontmatter into shapes the card spec forbids, and a vault
that fails validation the first time a human opens it is not initialized in any
useful sense.

Initialization MUST be idempotent: on an already-initialized vault - one where
that postcondition already holds - it verifies and succeeds without writing. It
MUST NOT overwrite a scaffold file that already exists, whatever that file
contains; a scaffold file is written only when absent. It therefore writes at
most the missing subset of the scaffold, and commits nothing when that subset is
empty.

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
  An initialization commit, which creates no card, is `hunt: init`. It appears
  at most once per branch: as the root commit on `main` for a vault this tool
  created, or on `VAULT_BRANCH` for a vault that predates the scaffold and was
  completed later (Section 5).
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

Allocation is a scan of the working tree. The numbering rules it implements are
those of `docs/card-spec.md` Section 2.2; this section states in Git terms what
that document states abstractly, and adds nothing to it.

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
  detecting and resolving that is a merge-time concern (Section 4), not a
  function of this contract.

---

## 8. Line Endings

Card files are LF only (`docs/card-spec.md` Section 3.1). That is a rule about
the bytes of a file; this section is what keeps it true inside a repository, and
what keeps a CR byte from ever reaching a remote.

The threat is not an author typing a CR. It is a Git client configured to
translate line endings - `core.autocrlf=true` is the default of the Windows
installer - which rewrites a checked-out card to CRLF and can record it back
that way. Nothing about the card format prevents that, and a CRLF card fails
both the byte rule and the re-render comparison that validation depends on.

- **`.gitattributes` is required.** The vault root MUST hold a `.gitattributes`
  that declares LF for every path it does not exempt, and it MUST NOT exempt a
  card file. It MUST be committed, and in a vault this tool initializes it MUST
  be present in the root commit on `main` (Section 4), so that it is in force on
  every branch ever forked from `main` and before any card is committed
  anywhere. A per-user or per-machine Git setting MUST NOT be relied on in its
  place: `.gitattributes` travels with the repository and overrides
  `core.autocrlf`, while a setting does neither.
- **The committed bytes are what matter.** Where `.gitattributes` is in force
  Git normalizes on check-in, so a working-tree file holding CRLF can still
  produce a clean commit. That is the intent, but it means an on-disk check no
  longer witnesses the guarantee. Validation MUST therefore read the committed
  blobs of the branch under examination and MUST report a CR byte in any of
  them. This is the check that survives someone deleting `.gitattributes`, and
  it is the one to run against `main` and against every merge candidate.
- **A missing `.gitattributes` is itself a finding.** Validation MUST report the
  absence of a vault-root `.gitattributes`, and MUST report one that exempts a
  card file, because the whole guarantee rests on that file.
- **The tool never records a CR.** Before committing, the tool MUST inspect the
  blobs it has staged and MUST refuse to commit if any holds a CR byte,
  whatever `.gitattributes` says and whatever the user's Git configuration
  says.
- **No CR reaches a remote.** No branch of the vault's remote, `main` or any
  other, may hold a card file containing a CR byte. The tool cannot enforce that
  itself, because it never pushes (Section 6). The enforcement is the two
  validation duties above, run in the vault's continuous integration and in a
  branch protection rule that rejects a push failing them.
