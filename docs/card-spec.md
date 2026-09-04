# Recurring Task-Card Schema (Obsidian, plain-text Markdown)

**Version:** 8
**Status:** normative schema and validation contract.
**Scope:** card format, cross-file invariants, and the rules a validator MUST
enforce, over a tree of card files rooted at a *card root*. Where that root
lives, how it is configured, what else may sit beside the card tree inside it,
and how any of it is version-controlled are out of scope: this document names
no path outside the card tree and no version-control system. Tool
implementation, CI wiring, and a stats layer are not specified here; their
*absence* does not weaken any rule below. Every rule below is enforceable today
by manual inspection and MUST be enforced by code once a validator exists.
**Changelog:** v8 freezes the whole body of an accepted run card (Section 6.1
and invariant 9 of Section 7): every section after `## Outcome` is as immutable
as the frontmatter, and the only permitted body change remains an appended
addition under `## Outcome`. v7 widens the optional run-card field `scope` (Sections 4 and
6.1) from a single quoted string to a flow sequence of one or more quoted
strings, written `scope: ["windows", "servers"]`. Each item obeys the shape v5
gave the scalar; the sequence MUST NOT be empty, and the way to record no scope
is still to omit the key. A card written against v5 carrying a bare quoted
string remains valid and MUST be read as a one-item sequence and re-rendered
in the spelling it uses: invariant 9 of Section 7 forbids editing an accepted
run, so a v5 card can never be migrated in place.
v6 adds the optional parent-card field `cadence` (Sections 4
and 5.1): an unquoted positive integer number of days naming how often the
task is meant to recur. It carries no enforced value set beyond "positive
integer"; a validator checks only that a present value is well formed. It is
positioned immediately after `status` and before the managed `latest_run`/
`latest_run_date` pair, which stay the last two keys. Because the field is
optional and new, every card written against v5 is still valid under v6.
v5 adds the optional run-card field `scope` (Sections 4 and
6.1): free text naming what a run covered, such as `windows` or `on-prem`. Its
value set is deliberately not defined and MUST NOT be enforced; a validator
checks only that a present value is well formed. Because the field is optional
and new, every card written against v4 is still valid under v5. Tags are
unchanged: they remain a parent-card field.
v4 makes this document self-contained. The rules that governed the card
root's non-card contents, the configuration file, the editor's state
directory, and Git branches moved out to the document that owns the root; a
contradiction between the two documents over which files may sit at the root is
resolved by that move. The history invariants (Section 7) and transition
validation (Section 8.2) are restated over an *accepted tree* and a *proposed
tree* (Section 1) rather than over a branch named `main`; their substance is
unchanged. v3 made card files ASCII only, added `open` to the run status enum,
removed `run_number` from frontmatter, pinned file conventions (Section 3.1) and
the parent's managed region (Section 5.2), and rebased number allocation on the
working tree (Section 2.2).

Keywords **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, **MAY** are
normative (RFC 2119 sense).

---

## 1. Scope and Model

- Every task is **recurring**.
- A **parent** (task-card) has zero or more **runs** (run-cards); each run is a
  single execution. A parent that has no run files yet is a legal state.
- Cards live in a tree under a **card root** (Section 3). Where that root is
  and how a reader finds it are out of scope; no rule here depends on its path
  or its name.
- External notes and attachments are out of scope, so every link this document
  constrains is a link between card files.
- **Accepted and proposed trees.** A card tree is in one of two roles at any
  moment. The **accepted tree** is the record: it is what has been reviewed and
  taken as final, and every immutability and numbering rule below is a
  statement about it. A **proposed tree** is a candidate to replace the
  accepted tree; within it files are drafts and MAY be freely edited, renamed,
  deleted, or renumbered. Which tree holds which role, and by what mechanism a
  proposed tree becomes the accepted one, are out of scope; the document that
  owns the card root supplies that binding.
- Two validation modes exist (Section 8): **snapshot validation** (is this tree
  internally consistent?) and **transition validation** (is this proposed tree
  legal given the accepted tree it would replace?).

---

## 2. Identifiers and Category Registry

### 2.1 Grammar

```
DIGIT3      := [0-9]{3}
CATEGORY    := "BSL" | "HNT" | "MTH"
PARENT_ID   := CATEGORY "-" DIGIT3
RUN_ID      := PARENT_ID "." DIGIT3
```

- `DIGIT3` is zero-padded, e.g. `007`, not `7`.
- `CATEGORY` is a closed set for this spec version. Adding a category is a
  spec revision (bump this document's version), not a runtime choice; there
  is no registry file. This version defines exactly:

  | Code | Directory |
  |---|---|
  | `BSL` | `baseline` |
  | `HNT` | `hunt` |
  | `MTH` | `math` |

- This table is the single source of truth in **both** directions: it maps a
  category code to the one directory name that code's cards live in, and it
  maps a directory name back to the one code its cards carry. No other
  mapping, alias, or fallback exists.
- IDs in frontmatter scalar values and in `[[wikilinks]]` MUST be the bare
  full ID: no `.md` suffix, no bracket characters inside the value, no
  aliases (`[[BSL-001|Baseline 1]]` is forbidden anywhere in a card file),
  no bare run numbers (`001`, `[[001]]`).
- A filename stem is globally unique across the card root. This is
  **derived**, not a second scan: the ID grammar, the rule of one index per
  parent directory, and the no-other-Markdown rule of Section 3 already force
  it. Uniqueness is **case-insensitive**: two stems differing only in case
  (`BSL-001` and `bsl-001`) are the same stem, and on a case-insensitive
  filesystem the same file. A tree containing both is invalid even where the
  filesystem can hold both.

### 2.2 Numbering

- Parent numbers, per category, and run numbers, per parent, MUST be
  **contiguous positive integers starting at 1**, zero-padded to 3 digits.
- **Precondition.** Numbers are allocated in a proposed tree, and only once it
  has been established that the proposed tree already contains every number
  present in the accepted tree. Allocating without having established this is
  forbidden; a tool that cannot establish it MUST refuse to allocate rather
  than guess. How it is established follows from whatever mechanism relates the
  two trees, and is out of scope here.
- Given that precondition, and given that no card file in the accepted tree is
  ever deleted, renamed, or renumbered (Section 7), every number ever assigned
  is present in the proposed tree. The next number to assign is therefore
  **(greatest number present in that tree) + 1**, determined by scanning that
  one tree alone. Nothing outside it is consulted - no history, no index, no
  other tree:
  - the next parent number for a category is derived from the parent
    directories present in that category directory;
  - the next run number for a parent is derived from the run files present in
    that parent directory;
  - an absent or empty directory yields `001`.
- 3-digit padding caps a category at 999 parents and a parent at 999 runs.
  A request that would allocate number 1000 MUST be reported as an explicit
  error. It MUST NOT wrap, silently widen the padding, or reuse a number.
  Widening the padding is a spec revision, out of scope here.
- Numbers are allocated per tree. Two proposed trees that each allocate
  without having incorporated the other's work will collide; detecting and
  resolving such a collision when they are reconciled is out of scope for this
  spec.

---

## 3. Filesystem Layout

```
task-cards/
  <category-dir>/
    <PARENT-ID>/
      <PARENT-ID>.md          # index (exactly one per parent dir)
      <PARENT-ID>.<NNN>.md    # run(s)
```

Concretely:

```
task-cards/
  baseline/BSL-001/BSL-001.md
  baseline/BSL-001/BSL-001.001.md
  baseline/BSL-001/BSL-001.002.md
  hunt/HNT-001/HNT-001.md
  hunt/HNT-001/HNT-001.001.md
```

**Path rules (MUST):**

- `task-cards/` above stands for the **card root**. It MAY be relocated; no
  rule depends on its absolute path or on its directory name.
- `<category-dir>` MUST be the exact directory from the Section 2.1 table.
- A parent directory is named exactly `<PARENT-ID>` and MUST live directly
  under its category directory.
- A parent directory MUST contain exactly one file `<PARENT-ID>.md` (the
  index) and zero or more files `<PARENT-ID>.<NNN>.md` (runs).
- No other Markdown file may exist under the card root: every card file is
  either that directory's index or a run belonging to that directory's
  parent.
- A category directory MUST contain nothing but parent directories, and a
  parent directory nothing but the card files above. Nothing else - not an
  attachment, not a template, not a tooling asset - may exist at either level.
- The card root MAY hold entries other than the category directories. What
  those are, and whether any are permitted at all, is out of scope here; the
  document that owns the card root enumerates them. This document constrains
  the category directories and their contents, plus the no-other-Markdown rule
  above, and nothing else about the root.
- The document that owns the card root MAY additionally exempt a closed, named
  set of *environment artifacts* - files written by an editor, a filesystem, or
  a version-control system rather than by an author - from the two rules above,
  wherever in the tree they appear. Such an exemption is a statement about that
  environment, not a relaxation of this document: a validator MUST treat every
  entry outside the exempted set as a violation, and no exemption may name a
  Markdown file.
- Only the final `.md` is a file extension; the `.` inside a run ID
  (`BSL-001.002`) is the parent/run separator, not part of the extension.

### 3.1 File Conventions

These apply to every card file. They exist so that the "contains exactly one
line" rules of Sections 5.2 and 6.2 are testable and so that a card can be
rendered and byte-compared (Section 8.1).

- **ASCII only.** Every byte of a card file MUST be either LF (`0x0A`) or a
  printable ASCII byte in the range `0x20`-`0x7E`. No em dash, en dash, arrow,
  non-breaking space, smart quote, or tab appears anywhere in a card file, in
  frontmatter or in body prose. The separator in the H1 (Section 5.2) and in
  run-history lines is U+002D HYPHEN-MINUS, written plainly as `-`.
- **Encoding.** Files are UTF-8 with no byte-order mark. The ASCII-only rule
  makes the byte stream identical to ASCII; UTF-8 is the declared encoding so
  that a future padding or category revision has room to move.
- **Line endings.** LF only. A CR byte (`0x0D`) anywhere in a card file is a
  violation, including in a CRLF pair.
- **Trailing newline.** A card file MUST end with exactly one newline: the
  last byte is LF and the byte before it is not LF. An empty file, a file with
  no final newline, and a file with a blank line at the end are all invalid.
- **Trailing whitespace.** No line may end with a space.
- **Frontmatter key order.** Keys MUST appear in exactly the order listed in
  Section 5.1 (parent) or Section 6.1 (run). A conditional key that is absent
  leaves the remaining keys in that same relative order; no key is reordered
  to close the gap.
- **Blank lines between blocks.** A *block* is the frontmatter, the H1, or an
  H2-or-deeper section together with its body. Consecutive blocks MUST be
  separated by exactly one blank line. There is no blank line between a
  heading and the first line of its body, and no blank line at the start of
  the file. Within a section body, blank lines are the author's to place as
  Markdown requires, except where a section's content is pinned exactly
  (Section 5.2). A section whose body is empty contributes its heading line
  and nothing else.

---

## 4. Field Types (applies to all frontmatter below)

| Field | Type | Format / constraint |
|---|---|---|
| `id` | string | bare `PARENT_ID` or `RUN_ID`, matches Section 2.1 grammar and the file's own path |
| `category` | string | one of the Section 2.1 codes; MUST equal the prefix of `id` |
| `parent` | string | bare `PARENT_ID`; MUST equal the ID of the containing directory |
| `tags` | array of strings | each item matches `^[a-z0-9][a-z0-9_-]*$`; MAY be empty (`[]`); MUST NOT be a bare scalar; written as a single-line flow sequence, items separated by `, ` |
| `status` (parent) | string enum | `active` \| `retired` |
| `status` (run) | string enum | `open` \| `complete` \| `void` |
| `cadence` | integer | positive integer, number of days; unquoted, no leading zero or sign; **no value set beyond "positive integer" is defined and none MUST be enforced** |
| `run_date`, `latest_run_date` | quoted string | `"YYYY-MM-DD"`, a valid Gregorian date; quoted to avoid YAML date-type coercion |
| `latest_run`, `previous_run` | string | bare `RUN_ID`, no `.md` |
| `scope` | array of quoted strings | one or more items, written as a single-line flow sequence with items separated by `, `; MUST NOT be empty (`[]`); each item is a single non-empty line, printable ASCII per Section 3.1, no leading or trailing space, MUST NOT contain `"` or `\`, and is quoted so that a value YAML would otherwise coerce stays a string. A bare quoted string (the v5 spelling) MUST be accepted, read as a one-item sequence, and re-rendered as it was found. **No value set is defined and none MUST be enforced** |

One body value is constrained here because tooling must reproduce it exactly:

| Value | Where | Format / constraint |
|---|---|---|
| `<task name>` | parent H1, Section 5.2 | non-empty; a single line; printable ASCII per Section 3.1; no leading or trailing whitespace; MAY contain hyphens |

**Run numbers are not a field.** A run's number is the numeric suffix of its
own filename (`BSL-001.002.md` is run 2). It MUST NOT appear in frontmatter;
`run_number` is not a permitted key in any card file. Because the H1's ID
prefix is fixed-length, `<task name>` is recovered by stripping the exact
prefix `# <PARENT-ID> - `, not by splitting on the separator, so a task name
containing a hyphen is unambiguous.

All frontmatter blocks MUST be delimited by `---` / `---`. Keys not listed
in Sections 5/6 MUST NOT appear (closed schema - unknown keys are a
validation failure, not silently ignored).

---

## 5. Parent Card (`<PARENT-ID>.md`)

### 5.1 Frontmatter

```yaml
---
id: BSL-001
category: BSL
tags: [dns, baseline, example]
status: active
cadence: 30
latest_run: BSL-001.002
latest_run_date: "2026-08-31"
---
```

`id`, `category`, `tags`, and `status` are REQUIRED, in that order.

`cadence` is **OPTIONAL**: a bare, unquoted positive integer naming how often,
in days, the task is meant to recur. When present it MUST immediately follow
`status` and MUST precede `latest_run`/`latest_run_date` when those are also
present. Its value set is deliberately not defined beyond "positive integer"
and MUST NOT be enforced further; a validator checks only that a present
value is well formed. Unlike most fields, `cadence` is exempt from the
immutability of invariant 9 (Section 7): on an accepted parent, it MAY be
added, changed to any other value satisfying Section 4, or removed, since
it is a live scheduling parameter rather than a record of what happened.

`latest_run` and `latest_run_date` are **conditional**: both MUST be present,
as the last two keys and in that order, if and only if the parent
directory contains at least one run file. A parent with no run files MUST omit
both; a parent with runs MUST carry both. One without the other is invalid.

No aggregate/count fields (e.g. run counts) are permitted here - such values
MUST be derived from the run files, never hand-maintained. `cadence` is not
such a field: it is an author-set scheduling parameter, not a value derived
from the run files.

**`latest_run` semantics:** it MUST always equal the run with the greatest run
number among that parent's run files, **regardless of that run's `status`** (an
`open` or `void` run can be `latest_run`). This keeps "latest" a single
unambiguous rule; consumers wanting only completed runs filter on `status`
themselves. A consequence, stated here so no reader has to discover it: when
the latest run is voided, the parent goes on transcluding a `void` run's
Outcome, and invariant 9 forbids editing the accepted parent to point
elsewhere.
That is intended. The remedy is a new run, not a correction.

**Retirement freeze:** when `status` is `retired`, `latest_run` and
`latest_run_date` MUST NOT change further - they remain at the values from
the moment of retirement. `retired` is terminal: once accepted, a retired
parent MUST NOT be reactivated to `active`.

**Retirement stops new runs:** a parent with `status: retired` MUST NOT
gain additional run files. Retirement does not alter existing run history,
IDs, `previous_run` chains, or the Latest-findings transclusion - it only
forecloses future runs and freezes the two pointer fields above.

Because retirement also forecloses new runs, the freeze can never put the two
pointers out of agreement with the run files; invariant 4 therefore holds
unconditionally, retired or not.

For a parent with no runs, both the freeze and the transclusion rules apply
vacuously: there are no pointer fields to freeze and no run to transclude, and
retiring such a parent leaves it permanently run-less.

### 5.2 Body - required structure

```markdown
# BSL-001 - <task name>

## Why
<purpose / context>

## Latest findings
![[BSL-001.002#Outcome]]

## Run history
- [[BSL-001.002]] - 2026-08-31
- [[BSL-001.001]] - 2026-08-01
```

Requirements:

- Exactly one H1, of the exact form `# <PARENT-ID> - <task name>`, where the
  separator is a space, a plain hyphen-minus, and a space.
- Exactly the three H2 sections `## Why`, `## Latest findings`,
  `## Run history`, in this order. Additional H2+ sections MAY follow
  `## Run history`; none may be inserted between the three required ones.
- `## Latest findings` contains exactly one line,
  `![[<latest_run>#Outcome]]`, where `<latest_run>` is the frontmatter
  `latest_run` value - or no lines at all when the parent has no runs.
- `## Run history` contains exactly one line per run file present for this
  parent, in the exact form `- [[<RUN-ID>]] - <run_date>`, sorted by run
  number **descending**, with no blank line inside the list. `<run_date>`
  matches that run's frontmatter `run_date` exactly, unquoted here. When the
  parent has no runs, the section contains no lines.

**Managed region and user region.** The parent card is co-owned. Every byte of
the *managed region* is derived from the parent's run files and MUST be
produced by rendering them; it MUST NOT be hand-maintained. The managed region
is:

- the `latest_run` and `latest_run_date` frontmatter lines, including whether
  they are present at all and their position as the last two keys; and
- the body from the `## Latest findings` heading line through the last line of
  the `## Run history` section - that is, both headings, the transclusion line,
  and the run-history lines, together with the single blank line between the
  two sections.

The *user region* is everything else: the `id`, `category`, `tags`,
`status`, and `cadence` frontmatter lines; the `<task name>` in the H1; the whole body of
`## Why`; and every H2+ section after `## Run history`, with its body.

The managed region is empty of content, though not of its two headings, when
the parent has no runs. Tooling MUST re-render the managed region in full from
the run files and MUST NOT patch it in place; a validator checks it by
re-rendering the whole card from its user region plus the run files and
comparing bytes. That single equality check subsumes the `latest_run`,
`latest_run_date`, Latest-findings and Run-history rules above, and invariant 4
of Section 7 as it applies to the parent. It does NOT subsume invariants 1 or 2:
the re-render derives the managed region *from* the run files, so a broken
`previous_run` chain or a gap in the run numbers is reproduced faithfully rather
than detected. Those two MUST be checked separately, against the run files
themselves.

---

## 6. Run Card (`<PARENT-ID>.<NNN>.md`)

### 6.1 Frontmatter

```yaml
---
id: BSL-001.002
parent: BSL-001
run_date: "2026-08-31"
previous_run: BSL-001.001   # REQUIRED unless the run number is 1
status: open
scope: ["windows", "servers"]   # OPTIONAL
---
```

`id`, `parent`, `run_date`, and `status` are REQUIRED, in that order.
`previous_run` is conditional: it MUST be present, between `run_date` and
`status`, for every run except run `001`, and MUST be absent for run `001`.
`scope` is OPTIONAL and, when present, MUST be the last key, after `status`.
`run_number` MUST NOT appear (Section 4).

**`scope` is free text, and its values are not a closed set.** It records what
this run covered - `["windows"]`, `["windows", "servers"]`, `["on-prem"]`, or
any phrase the hunter finds useful, one item or several. A validator MUST check
the *shape* given in Section 4 and MUST NOT check any item against a list,
vocabulary, or registry: no such list exists, and this document defines none.
The order of items carries no meaning, and no rule elsewhere derives from it.
Two runs of the same parent MAY carry unrelated scopes, or none at all; nothing
elsewhere in this document derives from, aggregates, or cross-checks the field.
A parent card has no `scope`, and scope is not a tag: `tags` remains a
parent-card field (Section 5.1) and gains no run-card counterpart here.

Being an ordinary run field, `scope` falls under invariant 9 of Section 7: once
a run has been accepted, its `scope` MUST NOT be added, changed, or removed.
The remedy for a run recorded with the wrong scope is the remedy for any other
mistaken run - a new run, not a correction.

**Status lifecycle.** A run is created with `status: open`, meaning the
execution is underway and its `## Outcome` is not yet written. Status advances
along the chain `open -> complete -> void`. Each step is one-way and no step
may be skipped. `complete` asserts that the run finished and its Outcome
records what it found; **only a human sets `complete`**, and tooling MUST NOT
write it, because tooling cannot know that a finding exists.

**At most one `open` run per parent.** A run is a single execution; it is
finished before the next is started. Creating a second run while one is still
`open` is a violation (Section 7, invariant 5).

**No forward pointer.** Run frontmatter deliberately has no `next_run`
field. A forward pointer on run *N* would have to be written when run
*N+1* is created - after run *N* has already been accepted - which is exactly
the kind of field mutation Section 7 (invariant 9) forbids. Forward traversal
(oldest to newest) is done by sorting a parent's runs by run number, not by
chain-walking; that sort is cheap and requires no mutation of accepted files.

**Void runs:** a run that was accepted in error MUST NOT be deleted, renamed,
or renumbered. Instead, exactly one field MAY change once the run has been
accepted: `status`, advancing along the chain above. No other field (`id`,
`parent`, `run_date`, `previous_run`) may ever change thereafter, and the
file's number, being its filename, cannot change at all. The run's
`## Outcome` body text MAY receive an appended explanation but the heading and
prior content MUST NOT be altered or removed, and any section after
`## Outcome` MUST NOT be added, removed, or edited (invariant 9, Section 7).
A `void` run remains part of the
`previous_run` chain and remains eligible to be `latest_run` (Section 5.1).

### 6.2 Body - required structure

```markdown
Part of: [[BSL-001]]
Previous: [[BSL-001.001]]

## Outcome
<findings from this run>
```

- The first non-empty line MUST be exactly `Part of: [[<parent>]]`. Whether a
  blank line separates it from the closing frontmatter fence is not left to
  chance: Section 3.1 requires exactly one.
- The line immediately after it MUST be exactly `Previous: [[<previous_run>]]`
  for every run except run `001`, which MUST omit this line entirely (no empty
  placeholder). The two lines form one block with no blank line between them.
- Exactly one `## Outcome` heading MUST exist; this exact heading text is
  the transclusion anchor the parent's Latest-findings section depends on
  and MUST NOT be changed. Additional H2+ sections MAY follow `## Outcome`.
- The `## Outcome` body of an `open` run MAY be empty.

---

## 7. Cross-File and Transition Invariants

Invariants 1-5 MUST hold for every parent directory of the accepted tree;
invariant 6 is tree-wide, as is the filename-uniqueness rule of Section 2.1
that it depends on. Invariants 7-10 relate a proposed tree to the accepted tree
it would replace rather than describing any one tree, and so are checkable only
in transition validation (Section 8.2):

1. **Chain integrity.** Sort the parent's run files by their filename-derived
   run number ascending. Run `001` has no `previous_run`. Every other run's
   `previous_run` equals the ID of the immediately preceding run in that sort
   - no skips, no forward references, no references to another parent, to
   itself, or to a nonexistent run. A parent with no run files satisfies this
   vacuously.
2. **Numbering contiguity.** The run numbers present in a parent directory,
   read from the run filenames, are exactly `1..N` with no gaps and no
   duplicates; `N` MAY be 0. The parent numbers present in a category
   directory are exactly `1..M` with no gaps; `M` MAY be 0 (Section 2.2).
3. **`category` / `parent` consistency.** A run's `parent` field, its path,
   and the prefix of its own `id` all agree; a parent's `category` field
   equals the prefix of its own `id` and equals the Section 2.1 code for its
   containing directory.
4. **`latest_run` agreement.** If the parent directory contains at least one
   run file, the parent's `latest_run` equals the run with the greatest run
   number in that directory and `latest_run_date` equals that run's
   `run_date`. If it contains none, both keys are absent (Section 5.1).
5. **At most one `open` run.** A parent directory contains no more than one
   run file with `status: open` (Section 6.1).
6. **Reference direction.** A link in a card file that targets a task other
   than the one whose directory the file lives in MUST target that task's
   parent index (`[[<PARENT-ID>]]`), never one of its runs. Links within a
   parent's own files - the `Previous:` line, the run-history list, the
   latest-findings transclusion, and prose references to sibling runs - MUST
   target run files as specified in Sections 5 and 6; that is not a violation
   of this rule.

**Transition invariants (not visible in a single-tree snapshot).** Below,
*accepted* qualifies a number or a card file present in the accepted tree, and
each invariant constrains what the proposed tree that would replace it may do:

7. No parent or run number, once accepted, is ever reused for a different card.
8. No accepted card file is ever deleted, renamed, or moved.
9. No field of an accepted run card changes, except `status`, advancing one
   step at a time along `open -> complete -> void` (Section 6.1). The only
   body change on an accepted run is an appended (not replacing) addition
   under `## Outcome`; every section after `## Outcome` is frozen exactly as
   the frontmatter is, so a section is never added, removed, or edited
   there once the run is accepted. No field of an
   accepted parent card changes, except `status` (`active -> retired`,
   one-way), `cadence` (freely, to any other value satisfying Section 4, or
   removed), and, only up to the moment of retirement, `latest_run`/
   `latest_run_date` advancing to a newly added run. The parent's managed
   body sections (Section 5.2) change only as a consequence of a run file
   being added.
10. `retired` never reverts to `active`.

---

## 8. Validation Requirements

A conforming validator MUST implement two modes:

### 8.1 Snapshot validation

Given a single card tree, check Sections 3-6 and invariants 1-6 of Section 7.
This requires nothing but the files that tree currently holds.
Sections 5.2 and 6.2 are checked by parsing each card, re-rendering it
from its user region plus the run files present, and comparing bytes. Section
3.1 MUST be checked directly over the whole file, independently of that
comparison: the user region is copied verbatim into the re-render, so a CRLF,
a non-ASCII byte or a missing trailing newline inside it would appear in both
sides of the comparison and survive it.

### 8.2 Transition validation

Given a proposed tree and the accepted tree it would replace, additionally
check invariants 7-10 of Section 7: nothing accepted was deleted, renamed,
moved, renumbered, or reused, and changes to accepted run and parent cards are
limited to the permitted one-way transitions.

Both modes are validation contracts required by this spec regardless of
whether an automated validator currently exists; until one exists, both are
checked by manual inspection against the rules above, not against a lesser
standard.
