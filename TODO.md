# TODO
*tasks by priority*

# Auditability and version control
- [ ] numbering resolution across branches; a main-transition, run at merge
  time, to reject or resolve conflicts: card-spec 8.2, `hunt validate --against
  <rev>`. Not implemented; the workflow carries a placeholder step for it.

# Task cards
## Tags generation
- by default, add `<category>` as a tag; 
# Run cards
## Scope
- make the scope frontmatter field a list that may contain one or more items, like `scope: [windows,server]`; Assignable at creation with `hunt run --id <id> --scope windows,server` (comma separated, unquoted, no space, 1+ items)

# Future
- Make task and/or run card generation possible using the obsidian app?
