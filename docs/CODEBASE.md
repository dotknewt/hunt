# Codebase reference

A map of the `hunt` source tree: what each file is for, what its functions do,
and what it depends on. The normative behaviour lives in
[`card-spec.md`](card-spec.md) and [`vault-spec.md`](vault-spec.md); this file
describes the code that implements them. A code-review section at the end lists
observations that were deliberately **not** applied.

## Layout

```
pyproject.toml        setuptools package "hunt"; console script hunt = hunt.cli:main
hunt.conf             tracked config with empty values (CI enforces it stays empty)
src/hunt/
  __init__.py         HuntError, the base of every domain error
  __main__.py         `python -m hunt` -> cli.main
  cli.py              argparse front end; one cmd_* function per subcommand
  config.py           hunt.conf discovery, parsing, validation and rewriting
  cards.py            card model: ids, paths, numbering, parse and render
  vault.py            every git interaction, plus path and branch safety
  validate.py         read-only whole-vault / per-parent validation -> Findings
  scaffold.py         files `hunt init` drops into a vault (.gitattributes, CI, .obsidian)
  complete.py         candidate producers for shell tab completion
tests/                pytest; conftest.py has the shared fixtures
docs/                 specs, agent notes, references
```

Runtime dependencies: Python 3.11+, `PyYAML` (frontmatter), `shtab` (completion
scripts, imported lazily so the CLI works without it), and a `git` binary on
`PATH` (called via `subprocess`, never a Python git library). Dev: `pytest`.

Internal import graph (arrows point at the importer's dependency):

```
cli -> cards, complete, config, scaffold, vault, validate
validate -> cards, vault
scaffold -> cards, vault
complete -> cards, config
cards, config, vault -> hunt (HuntError) only
```

## Command flow and exit codes

| Command | Path through the code |
|---|---|
| `hunt init` | `cli.cmd_init` -> `_locate_config` / `_init_values` -> `config.write_config` -> `vault.init` (with `scaffold.scaffold` as the root-commit `prepare` hook) -> `vault.sweep` -> scaffold again if the vault already existed -> `vault.commit` on the working branch |
| `hunt new` | `cmd_new` -> `config.load_configured` -> `vault.sweep`, `vault.ensure_writable` -> `cards.next_parent_number` -> `cards.new_parent` / `render_parent` -> `cli._write` (guarded by `vault.safe_path`) -> `vault.commit` |
| `hunt run` | `cmd_run` -> same preamble -> `cards.load_parent`, `load_runs` (refuses retired parent or an open run) -> `next_run_number`, `new_run` -> writes the run card and re-renders the parent index -> one commit with both |
| `hunt validate [--id]` | `cmd_validate` -> `validate.validate_vault` or `validate_parent_dir` (run-id filter applied in cli) -> prints `path: code: message` per finding |
| `hunt completion <shell>` | `cmd_completion` -> `shtab.complete(build_parser())` |
| `hunt __complete <kind>` | hidden; `cmd_hidden_complete` -> `complete.parent_ids` / `categories` |

Exit codes: `0` success or no findings; `1` any `HuntError` (domain refusal) or
at least one finding; `2` `ConfigUnset` (hunt.conf present but values empty).
argparse errors also exit 2.

---

## `src/hunt/__init__.py`

`HuntError(Exception)`: base class. `cli.main` catches it and prints one
`hunt: <message>` line to stderr.

## `src/hunt/cli.py`

Depends on: every other module. Only place that prints, prompts, or reads
`sys.argv`.

Constants
- `_COMPLETION_SHELLS`: `zsh`, `bash`, `powershell`.

Functions
- `_category`, `_task_name`, `_parent_id`, `_card_id`, `_scope`, `_run_date`:
  argparse `type=` validators wrapping `cards.is_valid_*`; raise
  `ArgumentTypeError` with the expected shape.
- `_guard(config, path)`: re-runs `vault.safe_path` on a card path right before
  writing, so a symlinked category or parent directory cannot redirect a write.
- `_write(config, path, text)`: `_guard` + `mkdir -p` + `cards.write_card`.
- `_warn(message)`: `hunt: warning:` line on stderr; passed to `scaffold`.
- `_confirm(question, assume_yes)`: y/N prompt; refuses when stdin is not a tty
  (nobody can answer) unless `--yes`.
- `_locate_config(args)`: which hunt.conf `init` will write. `$HUNT_CONF`
  pointing at a missing file is an error; otherwise a missing file is created in
  the cwd only if flags were given.
- `_init_values(args, config, conf)`: keys to write; prompts before replacing a
  value that is already set and differs.
- `_sweep(vault_path)`: deletes OS artifacts via `vault.sweep` and prints each.
  Not called by `validate` (a read-only command must not delete).
- `cmd_init`, `cmd_new`, `cmd_run`, `cmd_validate`, `cmd_completion`,
  `cmd_hidden_complete`: one per subcommand; see the flow table above. All
  take `(args, today)`; `today` is injected for tests.
- `_dynamic(kind, function)`: shtab `.complete` descriptor. Every shell
  shells out to `hunt __complete <kind>` so no vault knowledge lives in shell
  script.
- `build_parser()`: argparse tree. `__complete` gets no `help=` at all, which
  is what hides it (help=SUPPRESS would print the literal sentinel).
- `main(argv=None, today=None)`: no args prints help and exits 0; maps
  `ConfigUnset` to exit 2 with `_unset_help`, other `HuntError` to exit 1.

## `src/hunt/config.py`

Depends on: `hunt.HuntError`, stdlib. Implements vault-spec 1-2.

Constants
- `CONF_NAME = "hunt.conf"`, `USER_CONF = ~/.config/hunt/hunt.conf`.
- `_KEYS`: `VAULT_PATH`, `VAULT_BRANCH`, the whole schema.
- `_LINE_RE`: `KEY="value"` lines only; anything else is passed through (comments).
- `MAIN_BRANCH = "main"`; `_BRANCH_RE`: git ref-name subset.

Classes
- `ConfigError(HuntError)`: malformed or unreadable configuration.
- `ConfigUnset(ConfigError)`: keys present but empty. Distinct because it is the
  expected state of a fresh checkout and gets exit 2.
- `Config` (frozen dataclass): `vault_path`, `vault_branch` (None when empty),
  `path` (the file they came from). `unset` property lists empty keys.

Functions
- `user_config()`: `USER_CONF` expanded against the live `$HOME`.
- `find_config(start=None)`: `$HUNT_CONF` -> per-user file -> walk up from
  `start`/cwd. Does not stop at repo boundaries or `$HOME`.
- `load_config(path=None)`: parse and validate; empty values become `None`.
- `require_configured(config)`: raise `ConfigUnset` if anything is `None`.
- `load_configured(path=None)`: `find` + `load` + `require`.
- `_vault_path(conf, raw)`: must be absolute after `~/` expansion; rejects
  `~user`, `.` and `..` components.
- `_branch(conf, branch)`: rejects `main`, leading `-` (would parse as a git
  option), non-printable, and non-ref-name strings.
- `write_config(path, values)`: rewrites matching lines in place and appends
  missing keys in schema order, keeping comments. Atomic write (`.hunt-tmp`,
  fsync, `os.replace`) and the temp file is re-parsed before it replaces the
  original.

## `src/hunt/cards.py`

Depends on: `yaml`, `hunt.HuntError`. Implements card-spec: ids, file layout,
number allocation, parsing and canonical rendering. No git and no printing.

Constants
- `CATEGORIES` (`BSL`/`HNT`/`MTH` -> directory name), `DIRECTORIES` (inverse),
  `CATEGORY_ALIASES` (`b`/`h`/`m` shorthands), `MAX_NUMBER = 999`.
- Status strings and tuples: `PARENT_STATUSES` (active, retired),
  `RUN_STATUSES` (open, complete, void).
- Key schemas: `PARENT_KEYS`, `PARENT_REQUIRED_KEYS`, `RUN_KEYS`,
  `RUN_REQUIRED_KEYS`, `FORBIDDEN_KEYS` (`run_number`). Order matters: it is
  the canonical frontmatter order.
- Section titles `WHY`, `LATEST_FINDINGS`, `RUN_HISTORY`, `OUTCOME`;
  `PARENT_SECTIONS` in canonical order.
- Regexes: `PARENT_RE` (`BSL-001`), `RUN_RE` (`BSL-001.002`), `TAG_RE`,
  `SCOPE_RE` (printable ASCII minus `"` and `\`), `DATE_RE`, `_HEADING_RE`
  (`##`..`######`), `_KEY_RE` (textual top-level frontmatter key, used for
  order/duplicate checks that YAML loading would lose), `_ALIAS_RE`
  (`[[a|b]]`, forbidden), `_LINK_RE` (any `[[...]]`).

Classes
- `CardError(HuntError)`: malformed card or allocation refusal; carries a short
  `code` (e.g. `FM-BAD-ID`) that `validate.py` maps to a finding code.
- `ParentId(category, number)`, `RunId(parent, number)`: NamedTuples.
- `Parent(frontmatter, name, why, extra)`: validating properties `id`,
  `category`, `tags`, `status`, `latest_run`, `latest_run_date`. `extra` is
  the body after the three known sections, preserved verbatim.
- `Run(frontmatter, outcome, extra)`: properties `id`, `parent`, `run_date`,
  `previous_run`, `status`, `scope`.

Functions
- `category_spellings()`: every accepted `--category` spelling, help-text order.
- Frontmatter accessors `_string`, `_optional_string`, `_optional_date`,
  `_date_text` (rejects a YAML-parsed `date` object: dates must be quoted
  strings so the file round-trips byte for byte), `_fields(card, keys)`.
- `is_valid_tag/scope/date/task_name/parent_id/run_id`: pure predicates.
- `load_frontmatter(block)`: public alias of `_load_frontmatter`.
- `find_links(text)`, `find_alias_links(text)`: raw wikilink contents.
- `resolve_category(value)`: code or directory name, case-insensitive -> code.
- `parent_id`, `run_id`, `parse_parent_id`, `parse_run_id`, `card_filename`:
  id <-> string conversions.
- `category_dir`, `parent_dir`, `parent_path`, `run_path`: filesystem layout
  `<vault>/<category dir>/<PARENT>/<PARENT>.md` and `<PARENT>.<NNN>.md`.
- `run_number_from_filename(path)`: number from a run filename, or None.
- `next_parent_number(vault, code)`: scans the category directory, refuses
  case-insensitive stem collisions, returns max+1 (gaps are never reused).
- `next_run_number(vault, parent)`: same for run files.
- `_check_case_collision(names, subject)`, `_next_number(numbers, subject)`
  (raises at `MAX_NUMBER`), `_run_files(vault, parent)`.
- `read_card(path)`: read bytes and decode UTF-8; undecodable input is a
  `CardError` (`FILE-NON-ASCII`). Pure-ASCII is enforced later by validation.
- `write_card(path, text)`: atomic write (`.hunt-tmp`, fsync, `os.replace`).
- `load_parent`, `load_runs`: read + parse.
- `new_parent(parent, name, tags, why)`, `new_run(run, run_date, previous_run,
  scope)`: fresh in-memory cards.
- `_check_name(name)`: task-name validity.
- `_FrontmatterLoader(yaml.SafeLoader)` + `_construct_mapping`: SafeLoader
  subclass whose mapping constructor rejects duplicate keys (PyYAML silently
  keeps the last one). Subclassed so other `yaml.load` calls are unaffected.
- `split_frontmatter(text)`: `(block, body)` or raises on a missing fence.
- `frontmatter_key_order(text)`: textual key list, duplicates included.
- `_load_frontmatter(block)`: YAML -> dict with type checks.
- `parse_parent(text)`, `parse_run(text)`: full file -> `Parent`/`Run`;
  enforce H1 `# ID - name`, `Part of:`/`Previous:` lines, section presence
  and order.
- `_first_content`, `_split_sections`, `_section_body`, `_sections_from`:
  body-slicing helpers keyed on `_HEADING_RE`.
- `render_parent(parent, runs)`, `render_run(run)`: canonical text. Validation
  compares files byte for byte against these, so they define the only accepted
  formatting.
- `_frontmatter(keys)`, `_section(title, body)`: rendering primitives.

## `src/hunt/vault.py`

Depends on: `hunt.HuntError`, `config.Config` (type only), `subprocess`.
Every `git` call in the program goes through `_git`. Implements vault-spec 3-4.

Constants
- `MAIN_BRANCH`, `OS_ARTIFACTS` (`.DS_Store`, `Thumbs.db`), `ROOT_FILES`
  (`.gitignore`, `.gitattributes`), `INIT_SUBJECT = "hunt: init"`.

Functions
- `_git(vault, *args, check=True)`: `git -C <vault> ...` with text output;
  non-zero exit -> `VaultError` unless `check=False`.
- `_head_branch`, `_has_branch`, `_has_commits`: small queries.
- `is_repo(vault)`: true only if `vault` is itself the repository top level, not
  a subdirectory of one.
- `_enclosing_repo(vault)`: the repo a not-yet-initialised vault would be
  nested inside, if any.
- `init(vault, branch, prepare=None)`: refuses a symlink or a path inside another
  repo; `git init -b main`; calls `prepare(root)` (scaffold), stages, refuses CR
  bytes, root commit (`--allow-empty`), then creates/checks out `branch`.
  Returns the paths `prepare` created if they went into the root commit.
- `current_branch`, `is_clean`, `contains_main(vault, branch)` (branch has
  main's tip as ancestor).
- `ensure_writable(config)`: the pre-write gate for `new`/`run`: repo exists,
  on the configured branch, branch is not main and contains main, tree clean.
- `safe_path(vault, *parts)`: joins and refuses any symlink component or a
  result outside the vault.
- `_relative(vault, path)`: POSIX-style path relative to the vault for git.
- `ensure_on_branch(vault, branch)`: refuses if HEAD is not `branch`. Called
  before staging and again right before `commit` so a branch switch in between
  is caught.
- `commit(vault, paths, message, branch)`: explicit `git add` of exactly
  `paths`, CR refusal, commit.
- `_staged_blob`, `_refuse_staged_cr`: read staged content via `git show
  :<path>` and reject `\r`.
- `text_attributes(vault, paths)`: `git check-attr -z` parsed in
  (path, attr, value) triples; used by validate to confirm `text=auto eol=lf`.
- `sweep(vault)`: delete `OS_ARTIFACTS` anywhere under the vault; returns them.
- `tracked_blobs(vault, revision="HEAD")`: `(path, bytes)` for every tracked
  blob, one `git show` each.
- `ignored(vault, paths)`: `git check-ignore --no-index --stdin -z`; exit 0 and
  1 are both fine (1 = nothing ignored).

## `src/hunt/validate.py`

Depends on: `cards`, `vault`. Read-only. Produces `Finding` objects, never
raises for card problems (only for I/O outside the vault contract).

Constants
- `VAULT_DIRS`: `.git`, `.github`, `.obsidian`, the only non-category
  directories allowed at the root.
- `_QUOTE_LIMIT = 120`: max chars of offending text quoted in a message.
- `_CARD_ERROR_CODES`: `CardError.code` -> finding code; unmapped codes become
  `render.parse-error`.

Classes
- `Finding(path, code, message)`: frozen dataclass; `path` is vault-relative.
- `_ParentScan(parent, directory, index, runs)`: what `_scan_parent` found for
  one parent directory before any file is opened.

Entry points
- `validate_vault(vault_path)`: root entries -> `_scan_category` per category
  directory -> per-category `_check_parent_numbers` -> `_check_parent` per
  scan -> `_stem_collisions` -> `_check_git` -> `_ordered`.
- `validate_parent_dir(vault_path, parent_id)`: the same for one parent; no git
  or numbering checks.

Pipeline helpers
- `_card_paths(categories)`: every card path found, for the git checks.
- `_check_git(vault, card_paths, findings)`: silent if not a repo. Reports a
  missing `.gitattributes`, cards without `text=auto eol=lf`, cards hidden by
  `.gitignore`, and CR bytes in committed blobs (`bytes.crlf-committed`).
- `_entries`, `_scan_category`, `_scan_parent`, `_stray_file`, `_note_stem`,
  `_stem_collisions`: directory walk; stray files, bad names, missing index,
  case-insensitive stem duplicates.
- `_check_parent_numbers`: `invariant.number-gap` across a category.
- `_check_parent(scan, findings)`: runs first, then the index. If any run file
  failed to parse, the index re-render is skipped (it could not be reproduced)
  and only its frontmatter is checked.
- `_check_run_file` / `_check_index_file`: bytes -> links -> frontmatter ->
  parse -> render -> compare.
- `_read_text`, `_check_bytes` (empty, non-ASCII, control chars, CR, missing or
  extra trailing newline, trailing whitespace), `_line(data, offset)`.
- `_check_frontmatter`, `_check_keys` (duplicates, forbidden, unknown, missing,
  order), `_check_values`, `_check_category`, `_check_tags`, `_check_scope`.
- `_check_links`: aliases forbidden; links must point at the parent or a
  sibling run in the allowed direction.
- `_parse`, `_render`, `_compare` (reports the first differing line as
  `render.mismatch`).
- `_check_chain` (`Previous:` chain), `_check_numbering` (run gaps),
  `_check_open_runs` (at most one open run).
- `_card_error`, `_brief`, `_show`, `_ascii`: message formatting;
  `_ordered`: stable sort by path then code.

Finding code families: `bytes.*` (encoding and line endings), `path.*`
(layout, names, git hygiene), `frontmatter.*` (keys and values), `render.*`
(body structure and canonical-text mismatch), `invariant.*` (cross-card rules:
chain, numbering, links, single open run).

## `src/hunt/scaffold.py`

Depends on: `cards`, public `vault.ignored` / `vault.safe_path` / `VaultError`,
`json`. Files `hunt init` adds to a vault, each written only if absent.

- `GITATTRIBUTES` (`* text=auto eol=lf`), `GITIGNORE`, `WORKFLOW`
  (`.github/workflows/hunt.yml`: a `validate` job running `hunt validate` and a
  `line-endings` job; the merge-time transition check is a placeholder step),
  `APP`, `CORE_PLUGINS`, `TYPES` (Obsidian settings: frontmatter shown as
  source, every key typed `text`, system trash, unsupported files hidden).
- `_json(value)`: two-space indented, newline-terminated JSON.
- `files()`: path -> content mapping. `missing(vault)`: which are absent.
- `scaffold(vault, warn=None)`: writes the missing files; skips any that the
  vault's `.gitignore` hides and reports through `warn`. Returns created paths.
- `_write(path, text)`: asserts ASCII, LF only, newline-terminated.

## `src/hunt/complete.py`

Depends on: `cards`, `config`. Called by `hunt __complete` from shell
completion scripts, so it must never fail loudly.

- `_quiet(default)`: decorator that swallows every exception and returns
  `default`; set `HUNT_COMPLETE_DEBUG=1` to see the traceback instead.
- `categories()`: `cards.category_spellings()`.
- `parent_ids()`: parent ids found by scanning the configured vault's category
  directories (skips symlinks; no config -> empty list).

## Tests

`tests/conftest.py`: `run_git`, `write_file` helpers; autouse `clean_env`
(isolates `$HOME`, `$HUNT_CONF`, cwd); `vault` fixture (initialised temp vault
with a hunt.conf pointing at it). `test_cards.py`, `test_config.py`,
`test_vault.py`, `test_validate.py` are unit tests per module; `test_cli.py`
drives `cli.main` end to end. Run with `uv sync --locked && uv run pytest`.

---

## Code review findings (not applied)

The review task was documentation-only, so none of these were changed. They are
listed for a future pass, roughly by usefulness.

1. **`vault.tracked_blobs` spawns one `git show` per tracked file.** On a large
   vault `hunt validate` will be dominated by process start-up. `git cat-file
   --batch` fed from `ls-tree` would read every blob in one process.
2. **Transition validation is unimplemented.** card-spec 8.2 (`hunt validate
   --against <rev>`) is tracked in `TODO.md`; the scaffolded workflow carries an
   echo placeholder step. Cross-branch numbering conflicts are therefore only
   caught after merge.
3. **Applied:** `scaffold.py` now calls public `vault.ignored`; it no longer
   imports private `vault._git` or duplicates the ignore check.
4. **Applied:** category spellings now live in `cards.py`; `complete` and `cli`
   import directly without a cycle or lazy imports.
5. **`cards.find_links`** is `[raw for raw in _LINK_RE.findall(text)]`, a
   no-op list comprehension over a list. `_LINK_RE.findall(text)` is equivalent.
6. **`cards._next_number` and `validate._check_parent_numbers`** rebuild
   `set(numbers)` inside a comprehension, so the set is constructed once per
   candidate number. Hoisting it out is a one-line change with no behaviour
   difference.
7. **`cards.load_frontmatter`** is a bare alias of `_load_frontmatter`. Either
   rename the private one or drop the alias; the tests are the only caller.
8. **`validate._ParentScan.index`** is annotated `Path = None`; it should be
   `Path | None = None` to match the rest of the module's annotations.
9. **`scaffold.py` module docstring** has a line over the width the rest of the
   code keeps to.
10. **CI windows job is disabled** in the repo's own workflow. The line-ending
    guards are the part most likely to regress on Windows, so it is the platform
    that would benefit most from running.
11. **Design note, not a defect:** non-ASCII anywhere in a card, task name,
    scope or config is rejected. This is deliberate per the specs (byte-stable
    diffs), but it will surprise a user with a non-ASCII name and the error
    messages could say why.
