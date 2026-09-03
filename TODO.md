# TODO
*tasks by priority*

# Auditability and version control
- [x] separate repository `main` branch protected: `hunt init` scaffolds
  `.github/workflows/hunt.yml`; the branch rule itself is set on the remote
  (README, "Vault CI and branch protection")
- [x] CI validation; no ID/filename duplication: the `validate` job runs
  `hunt validate` on every merge candidate
- [x] verify and enforce line-endings as LF: `hunt validate` reads committed
  blobs, and the `line-endings` job checks them independently
- [ ] numbering resolution across branches; a main-transition, run at merge
  time, to reject or resolve conflicts: card-spec 8.2, `hunt validate --against
  <rev>`. Not implemented; the workflow carries a placeholder step for it.
