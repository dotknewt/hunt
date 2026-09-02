# TODO
*tasks by priority*

Automated template card creation for new tasks or new task runs for each given category
- creates cards in an external directory location; specified in a repo-local config file
- reference files live in `docs/references/cards`

# Auditability and version control
- separate repository `main` branch protected
- CI validation; no ID/filename duplication
- numbering resolution across branches; a main-transition, run at merge time, to reject or resolve conflicts.
