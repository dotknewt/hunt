# Recurring Task-Card Schema (Obsidian, plain-text Markdown)

**Status:** normative schema and validation contract.
**Scope:** card format, cross-file invariants, and the rules a
validator MUST enforce. Tool implementation, CI wiring, and a stats layer are
not specified here (Section 9); their *absence* does not weaken any rule
above — every rule below is enforceable today by manual inspection and MUST
be enforced by code once a validator exists.

Keywords **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, **MAY** are
normative (RFC 2119 sense).

---

## 1. Scope and Model

- Every task is **recurring**.
- A **parent** (task-card) has one or more **runs** (run-cards); each run is a single execution.
- The vault location is defined in  (`task-cards/`) is a Git repository. **`main` is the record.** All
  immutability and numbering rules apply to `main`. On a branch, files are
  drafts and MAY be freely edited, renamed, deleted, or renumbered.
- Two validation modes exist (Section 8): **snapshot validation** (is this
  tree internally consistent?) and **main-transition validation** (is this
  change to `main` legal given the preceding `main` tree?).

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

- IDs in frontmatter scalar values and in `[[wikilinks]]` MUST be the bare
  full ID: no `.md` suffix, no bracket characters inside the value, no
  aliases (`[[BSL-001|Baseline 1]]` is forbidden anywhere in a card file),
  no bare run numbers (`001`, `[[001]]`).
- A filename (its stem) MUST be globally unique across the entire vault
  (`task-cards/**`).

### 2.2 Numbering

- Parent numbers, per category, and run numbers, per parent, MUST be
  **contiguous positive integers starting at 1**, zero-padded to 3 digits.
- The next number to assign is **(greatest existing number on `main`) + 1**.
  Since numbers are never deleted, reused, or renumbered on `main` (Section
  7), the greatest existing number on `main` is always exactly the greatest
  number ever assigned — there is no separate history lookup.
- 3-digit padding caps a category at 999 parents and a parent at 999 runs.
  Exceeding this requires a spec revision to widen padding; out of scope
  here.

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

- `task-cards/` is the vault root. It MAY be relocated; no rule depends on its
  absolute path.
- `<category-dir>` MUST be the exact directory from the Section 2.1 table.
- A parent directory is named exactly `<PARENT-ID>` and MUST live directly
  under its category directory.
- A parent directory MUST contain exactly one file `<PARENT-ID>.md` (the
  index) and zero or more files `<PARENT-ID>.<NNN>.md` (runs).
- No other Markdown file may exist under `task-cards/**`: every card file is
  either that directory's index or a run belonging to that directory's
  parent.
- Only the final `.md` is a file extension; the `.` inside a run ID
  (`BSL-001.002`) is the parent/run separator, not part of the extension.
- Templates and any tooling assets MUST NOT live under `task-cards/`.

---

## 4. Field Types (applies to all frontmatter below)

| Field | Type | Format / constraint |
|---|---|---|
| `id` | string | bare `PARENT_ID` or `RUN_ID`, matches Section 2.1 grammar and the file's own path |
| `category` | string | one of the Section 2.1 codes; MUST equal the prefix of `id` |
| `parent` | string | bare `PARENT_ID`; MUST equal the ID of the containing directory |
| `tags` | array of strings | MAY be empty (`[]`); MUST NOT be a bare scalar |
| `status` (parent) | string enum | `active` \| `retired` |
| `status` (run) | string enum | `complete` \| `void` |
| `run_number` | integer | matches the run's filename numeric suffix exactly (e.g. filename `...002.md` → `run_number: 2`); unique and contiguous within its parent (Section 2.2) |
| `run_date`, `latest_run_date` | quoted string | `"YYYY-MM-DD"`, a valid Gregorian date; quoted to avoid YAML date-type coercion |
| `latest_run`, `previous_run` | string | bare `RUN_ID`, no `.md` |

All frontmatter blocks MUST be delimited by `---` / `---`. Keys not listed
in Sections 5/6 MUST NOT appear (closed schema — unknown keys are a
validation failure, not silently ignored).

---

## 5. Parent Card (`<PARENT-ID>.md`)

### 5.1 Frontmatter

```yaml
---
id: BSL-001
category: BSL
tags: [example, tag]
status: active
latest_run: BSL-001.002
latest_run_date: "2026-08-31"
---
```

All six keys are REQUIRED. No aggregate/count fields (e.g. run counts) are
permitted here — such values MUST be derived from the run files, never
hand-maintained.

**`latest_run` semantics:** it MUST always equal the run with the greatest
`run_number` among that parent's run files, **regardless of that run's
`status`** (a `void` run can be `latest_run`). This keeps "latest" a single
unambiguous rule; consumers wanting only completed runs filter on `status`
themselves.

**Retirement freeze:** when `status` is `retired`, `latest_run` and
`latest_run_date` MUST NOT change further — they remain at the values from
the moment of retirement. `retired` is terminal: a retired parent MUST NOT
be reactivated to `active` on `main`.

**Retirement stops new runs:** a parent with `status: retired` MUST NOT
gain additional run files. Retirement does not alter existing run history,
IDs, `previous_run` chains, or the Latest-findings transclusion — it only
forecloses future runs and freezes the two pointer fields above.

### 5.2 Body — required structure

```markdown
# BSL-001 — <task name>

## Why
<purpose / context>

## Latest findings
![[BSL-001.002#Outcome]]

## Run history
- [[BSL-001.002]] — 2026-08-31
- [[BSL-001.001]] — 2026-08-01
```

Requirements:

- Exactly one H1, of the exact form `# <PARENT-ID> — <task name>`.
- Exactly the three H2 sections `## Why`, `## Latest findings`,
  `## Run history`, in this order. Additional H2+ sections MAY follow
  `## Run history`; none may be inserted between the three required ones.
- `## Latest findings` contains exactly one line,
  `![[<latest_run>#Outcome]]`, where `<latest_run>` is the frontmatter
  `latest_run` value.
- `## Run history` contains exactly one line per run file present for this
  parent, in the exact form `- [[<RUN-ID>]] — <run_date>` (em dash), sorted
  by `run_number` **descending**. `<run_date>` matches that run's
  frontmatter `run_date` exactly.

---

## 6. Run Card (`<PARENT-ID>.<NNN>.md`)

### 6.1 Frontmatter

```yaml
---
id: BSL-001.002
parent: BSL-001
run_number: 2
run_date: "2026-08-31"
previous_run: BSL-001.001   # REQUIRED unless run_number == 1
status: complete
---
```

`previous_run` MUST be present for every run except the one with
`run_number: 1`, and MUST be absent for that one.

**No forward pointer.** Run frontmatter deliberately has no `next_run`
field. A forward pointer on run *N* would have to be written when run
*N+1* is created — after run *N* is already merged to `main` — which is
exactly the kind of post-merge field mutation Section 7 (invariant 10)
forbids. Forward traversal (oldest → newest) is done by sorting a parent's
runs by `run_number`, not by chain-walking; that sort is cheap and requires
no mutation of merged files.

**Void runs:** a run that reached `main` in error MUST NOT be deleted,
renamed, or renumbered. Instead, on `main`, exactly one field MAY change
after merge: `status`, from `complete` to `void` (one-way). No other field
(`id`, `parent`, `run_number`, `run_date`, `previous_run`) may ever change
post-merge. The run's `## Outcome` body text MAY receive an appended
explanation but the heading and prior content MUST NOT be altered or
removed. A `void` run remains part of the `previous_run` chain and remains
eligible to be `latest_run` (Section 5.1).

### 6.2 Body — required structure

```markdown
Part of: [[BSL-001]]
← [[BSL-001.001]]

## Outcome
<findings from this run>
```

- First line MUST be exactly `Part of: [[<parent>]]`.
- Second line MUST be exactly `← [[<previous_run>]]` for every run except
  `run_number: 1`, which MUST omit this line entirely (no empty placeholder).
- Exactly one `## Outcome` heading MUST exist; this exact heading text is
  the transclusion anchor the parent's Latest-findings section depends on
  and MUST NOT be changed. Additional H2+ sections MAY follow `## Outcome`.

---

## 7. Cross-File and Repository Invariants

These MUST hold for every parent directory on `main`:

1. **Chain integrity.** Sort the parent's run files by `run_number`
   ascending. The run with `run_number: 1` has no `previous_run`. Every
   other run's `previous_run` equals the ID of the immediately preceding
   run in that sort — no skips, no forward references, no references to
   another parent, itself, or a nonexistent run.
2. **Numbering contiguity.** `run_number` values for a parent are exactly
   `1..N` with no gaps (Section 2.2); parent numbers within a category are
   exactly `1..M` with no gaps.
3. **`category` / `parent` consistency.** A run's `parent` field, its path,
   and the prefix of its own `id` all agree; a parent's `category` field
   equals the prefix of its own `id` and equals the Section 2.1 code for its
   containing directory.
4. **`run_number` / filename agreement.** A run's `run_number` equals the
   numeric suffix of its own filename.
5. **`latest_run` agreement.** The parent's `latest_run` equals the run
   with the greatest `run_number` in its directory; `latest_run_date`
   equals that run's `run_date` (subject to the retirement freeze, §5.1).
6. **Every parent has ≥ 1 run.** A parent directory with zero run files is
   invalid.
7. **Reference direction.** Any link to a task from outside its own parent
   directory (external notes, other cards' bodies) MUST target the parent
   index (`[[<PARENT-ID>]]`), not an individual run. Links *within* a
   parent's own files (predecessor link, run-history list, latest-findings
   transclusion) MUST target run files as specified in Sections 5–6; this
   is not a violation of the external-reference rule.

**Repository history invariants (main-transition only, not visible in a
single-tree snapshot):**

8. No parent or run number, once it has existed on `main`, is ever reused
   for a different card.
9. No card file, once merged to `main`, is ever deleted, renamed, or moved.
10. On `main`, no field of a merged run changes except `status`
    (`complete → void`, one-way) and an appended (not replacing) addition
    under `## Outcome`. No field of a merged parent changes except
    `status` (`active → retired`, one-way) and, only up to the moment of
    retirement, `latest_run`/`latest_run_date` advancing to a newly added
    run.
11. `retired` never reverts to `active` on `main`.

---

## 8. Validation Requirements

A conforming validator MUST implement two modes:

### 8.1 Snapshot validation

Given the current `task-cards/` tree, check Sections 3–6 and invariants 1–7 of
Section 7. This requires no Git history — only the files currently present.

### 8.2 Main-transition validation

Given a proposed change (a merge/commit) and the preceding state of `main`,
additionally check invariants 8–11 of Section 7: nothing was deleted,
renamed, moved, renumbered, or reused, and merged-run/merged-parent field
mutations are limited to the permitted one-way transitions.

Both modes are validation contracts required by this spec regardless of
whether an automated validator currently exists; until one exists, both are
checked by manual inspection against the rules above, not against a lesser
standard.
