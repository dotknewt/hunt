from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from . import HuntError, cards, scaffold, vault
from .cards import CardError
from .config import (
    CONF_NAME,
    ConfigError,
    ConfigUnset,
    find_config,
    load_config,
    load_configured,
    require_configured,
    write_config,
)
from .validate import validate_parent_dir, validate_vault
from .vault import VaultError


# Typing conveniences, deliberately not in cards.py: cards.CATEGORIES mirrors
# the closed set of card-spec 2.1, and an input shorthand is not part of it.
_CATEGORY_ALIASES = {"b": "BSL", "h": "HNT", "m": "MTH"}


def category_spellings():
    """Every spelling --category accepts, in the order the help text lists them."""
    return (
        sorted(cards.CATEGORIES.values())
        + sorted(cards.CATEGORIES)
        + sorted(_CATEGORY_ALIASES)
    )


def _category(value):
    if isinstance(value, str) and value.lower() in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[value.lower()]
    try:
        return cards.resolve_category(value)
    except CardError:
        raise argparse.ArgumentTypeError(
            "invalid category %r (expected one of: %s)"
            % (value, ", ".join(category_spellings()))
        )


def _task_name(value):
    if not cards.is_valid_task_name(value):
        raise argparse.ArgumentTypeError(
            "invalid task name %r (expected a non-empty trimmed line of printable ASCII)"
            % value
        )
    return value


def _parent_id(value):
    if not cards.is_valid_parent_id(value):
        raise argparse.ArgumentTypeError(
            "invalid parent id %r (expected e.g. BSL-001)" % value
        )
    return value


def _card_id(value):
    if cards.is_valid_parent_id(value) or cards.is_valid_run_id(value):
        return value
    raise argparse.ArgumentTypeError(
        "invalid id %r (expected e.g. BSL-001 or BSL-001.002)" % value
    )


def _scope(value):
    if not cards.is_valid_scope(value):
        raise argparse.ArgumentTypeError(
            "invalid scope %r (expected a single non-empty line of printable ASCII, "
            "without a double quote, a backslash, or surrounding spaces)" % value
        )
    return value


def _run_date(value):
    if not cards.is_valid_date(value):
        raise argparse.ArgumentTypeError("invalid date %r (expected YYYY-MM-DD)" % value)
    return value


def _guard(config, path):
    """Re-check a card path through the vault's symlink and escape guard."""
    relative = Path(path).relative_to(config.vault_path)
    return vault.safe_path(config.vault_path, *relative.parts)


def _write(config, path, text):
    target = _guard(config, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    cards.write_card(target, text)
    return target


def _warn(message):
    print("hunt: warning: %s" % message, file=sys.stderr)


def _confirm(question, assume_yes):
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        # Refusing is the only safe answer: nobody is there to say no, and the
        # value already in the file was put there on purpose.
        return False
    try:
        answer = input(question)
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _locate_config(args):
    """The hunt.conf `hunt init` will write, and its current contents if any."""
    try:
        conf = find_config()
    except ConfigError as exc:
        if os.environ.get("HUNT_CONF"):
            # An explicit pointer at a missing file is a mistake, not a request
            # to create one somewhere else.
            raise
        if args.vault_path is None and args.vault_branch is None:
            # Nothing to write and nowhere to write it: say what would fix both.
            raise ConfigError(
                "%s; or run: hunt init --vault-path <PATH> --vault-branch <NAME>"
                % exc
            ) from exc
        return Path.cwd() / CONF_NAME, None
    # find_config ascends without stopping at a repository boundary or $HOME
    # (vault-spec 2), so say which file is about to be written.
    print("configuration: %s" % conf)
    return conf, load_config(conf)


def _init_values(args, config, conf):
    """Which keys to write, prompting before replacing a configured value."""
    requested = (
        ("VAULT_PATH", args.vault_path, lambda value: str(Path(value).expanduser())),
        ("VAULT_BRANCH", args.vault_branch, lambda value: value),
    )
    values = {}
    for key, flag, normalize in requested:
        if flag is None:
            continue
        existing = None if config is None else getattr(config, key.lower())
        if existing is None:
            values[key] = flag
            continue
        if str(existing) == normalize(flag):
            continue
        if not _confirm(
            'overwrite %s "%s" with "%s"? [y/N] ' % (key, existing, flag), args.yes
        ):
            raise HuntError(
                "refusing to overwrite %s in %s; pass --yes to replace it" % (key, conf)
            )
        values[key] = flag
    return values


def _sweep(vault_path):
    """Drop environment artifacts before the clean-tree check (vault-spec 3).

    A .DS_Store Finder wrote while nobody was looking must not be able to stand
    between the author and a card, and nothing authored it, so nothing is lost.
    `hunt validate` deliberately does not call this: deleting during a read-only
    command would be a surprise.
    """
    for removed in vault.sweep(vault_path):
        print("removed %s" % removed)


def cmd_init(args, today):
    conf, config = _locate_config(args)
    values = _init_values(args, config, conf)
    if config is None:
        # A new file gets the whole schema, empty where nothing was given, so
        # that what it holds is a readable configuration either way.
        values = {"VAULT_PATH": "", "VAULT_BRANCH": "", **values}
    if values:
        write_config(conf, values)
        print("wrote %s to %s" % (", ".join(sorted(values)), conf))
    config = require_configured(load_config(conf))

    prepare = lambda root: scaffold.scaffold(root, warn=_warn)  # noqa: E731
    in_root_commit = vault.init(config.vault_path, config.vault_branch, prepare=prepare)
    _sweep(config.vault_path)
    created = in_root_commit or scaffold.scaffold(config.vault_path, warn=_warn)
    if created and not in_root_commit:
        # The root commit is already written and the tool never commits on main
        # again (vault-spec 4), so an existing vault gets the scaffold on its
        # working branch instead.
        vault.commit(config.vault_path, created, vault.INIT_SUBJECT)
    for path in created:
        print("created %s" % path)
    print("initialized %s on %s" % (config.vault_path, config.vault_branch))
    return 0


def cmd_new(args, today):
    config = load_configured()
    _sweep(config.vault_path)
    vault.ensure_writable(config)
    number = cards.next_parent_number(config.vault_path, args.category)
    parent_id = cards.parent_id(args.category, number)
    # Not an argparse default: the id is unknown until after allocation.
    parent = cards.new_parent(parent_id, args.name or parent_id)
    path = _write(
        config,
        cards.parent_path(config.vault_path, parent_id),
        cards.render_parent(parent, []),
    )
    vault.commit(config.vault_path, [path], "hunt: new %s" % parent_id)
    print(parent_id)
    return 0


def cmd_run(args, today):
    config = load_configured()
    _sweep(config.vault_path)
    vault.ensure_writable(config)
    parent_path, parent = cards.load_parent(config.vault_path, args.id)
    if parent.status == cards.STATUS_RETIRED:
        raise CardError("%s is retired and MUST NOT gain further runs" % args.id)
    existing = cards.load_runs(config.vault_path, args.id)
    for _, run in existing:
        if run.status == cards.STATUS_OPEN:
            raise CardError(
                "%s already has an open run (%s); finish it first" % (args.id, run.id)
            )
    number = cards.next_run_number(config.vault_path, args.id)
    run_ident = cards.run_id(args.id, number)
    previous = existing[-1][1].id if existing else None
    run = cards.new_run(run_ident, args.date or today.isoformat(), previous, args.scope)
    runs = [card for _, card in existing] + [run]
    run_target = _write(
        config, cards.run_path(config.vault_path, run_ident), cards.render_run(run)
    )
    parent_target = _write(config, parent_path, cards.render_parent(parent, runs))
    vault.commit(
        config.vault_path, [run_target, parent_target], "hunt: run %s" % run_ident
    )
    print(run_ident)
    return 0


def cmd_validate(args, today):
    config = load_configured()
    if not config.vault_path.is_dir():
        raise VaultError("vault does not exist: %s" % config.vault_path)
    if not vault.is_repo(config.vault_path):
        raise VaultError("vault is not a git repository: %s" % config.vault_path)
    if args.id is None:
        findings = validate_vault(config.vault_path)
    elif cards.is_valid_parent_id(args.id):
        findings = validate_parent_dir(config.vault_path, args.id)
    else:
        parent = cards.parse_run_id(args.id).parent
        wanted = cards.card_filename(args.id)
        findings = [
            finding
            for finding in validate_parent_dir(config.vault_path, parent)
            if Path(finding.path).name == wanted
        ]
    for finding in findings:
        print("%s: %s: %s" % (finding.path, finding.code, finding.message))
    return 1 if findings else 0


# Every shell gets the same one-line shell-out to `hunt __complete`. No shell
# knows where the vault is, how a card is named, or that hunt.conf exists, so
# adding a shell is a matter of translating one call rather than reimplementing
# any of that in shell script.
_COMPLETION_SHELLS = ("zsh", "bash", "powershell")


def _dynamic(kind, function):
    return {
        "zsh": "($(hunt __complete %s 2>/dev/null))" % kind,
        "bash": function,
        "powershell": function,
        "preamble": {
            "bash": '%s(){ compgen -W "$(hunt __complete %s 2>/dev/null)" -- "$1"; }'
            % (function, kind),
            "powershell": "\n".join(
                [
                    "function %s {" % function,
                    "  param([string]$WordToComplete)",
                    "  (hunt __complete %s 2>$null) |" % kind,
                    '    Where-Object { $_ -like "$WordToComplete*" }',
                    "}",
                ]
            ),
        },
    }


def cmd_completion(args, today):
    # Imported here, not at module scope: the CLI must still run when shtab is
    # missing from the interpreter, which is exactly the case the tests create.
    import shtab

    print(shtab.complete(build_parser(), shell=args.shell), end="")
    return 0


def cmd_hidden_complete(args, today):
    from . import complete

    producers = {"ids": complete.parent_ids, "categories": complete.categories}
    for candidate in producers[args.kind]():
        print(candidate)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="hunt",
        description="Create and validate recurring task cards in the vault.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    init = subparsers.add_parser("init", help="initialize the vault repository and branch")
    init.add_argument(
        "--vault-path", metavar="<PATH>", help="set VAULT_PATH in %s" % CONF_NAME
    )
    init.add_argument(
        "--vault-branch", metavar="<NAME>", help="set VAULT_BRANCH in %s" % CONF_NAME
    )
    init.add_argument(
        "--yes",
        action="store_true",
        help="replace a configured value without asking (required when not a terminal)",
    )
    init.set_defaults(func=cmd_init)

    new = subparsers.add_parser("new", help="create a parent card")
    new.add_argument(
        "-c",
        "--category",
        required=True,
        type=_category,
        metavar="<category>",
        help="one of: %s (case-insensitive)" % ", ".join(category_spellings()),
    ).complete = _dynamic("categories", "_hunt_categories")
    new.add_argument(
        "--name",
        type=_task_name,
        metavar="<task name>",
        help="task name; defaults to the allocated parent id",
    )
    new.set_defaults(func=cmd_new)

    run = subparsers.add_parser("run", help="create the next run card for a parent")
    run.add_argument(
        "--id", required=True, type=_parent_id, metavar="<PARENT-ID>", help="parent id"
    ).complete = _dynamic("ids", "_hunt_ids")
    run.add_argument(
        "--date",
        type=_run_date,
        metavar="YYYY-MM-DD",
        help="run date; defaults to today",
    )
    run.add_argument(
        "--scope",
        type=_scope,
        metavar="<scope>",
        help="free-text scope of the run, e.g. 'windows servers'; omitted if unset",
    )
    run.set_defaults(func=cmd_run)

    validate = subparsers.add_parser("validate", help="validate the vault")
    validate.add_argument(
        "--id", type=_card_id, metavar="<ID>", help="restrict findings to one card"
    )
    validate.set_defaults(func=cmd_validate)

    completion = subparsers.add_parser(
        "completion", help="print a shell completion script"
    )
    completion.add_argument(
        "shell", choices=_COMPLETION_SHELLS, metavar="<shell>", help="target shell"
    )
    completion.set_defaults(func=cmd_completion)

    # No help= at all, which is what actually hides it: argparse formats a
    # subparser's pseudo-actions without re-checking SUPPRESS, so help=SUPPRESS
    # would print the literal "==SUPPRESS==" in `hunt --help`.
    hidden = subparsers.add_parser("__complete")
    hidden.add_argument("kind", choices=("ids", "categories"), metavar="<kind>")
    hidden.set_defaults(func=cmd_hidden_complete)

    return parser


def main(argv=None, today=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    try:
        return args.func(args, today or date.today())
    except ConfigUnset as exc:
        # Exit 2, the usage code: nothing is wrong with the vault, the tool has
        # not been told where it is. Keep it distinct from the exit 1 of a
        # domain error so a caller can tell "misconfigured" from "refused".
        print(_unset_help(exc), file=sys.stderr)
        return 2
    except HuntError as exc:
        print("hunt: %s" % exc, file=sys.stderr)
        return 1


def _unset_help(exc):
    return "\n".join(
        [
            "hunt: %s" % exc,
            "",
            "Edit that file, or run:",
            "    hunt init --vault-path <PATH> --vault-branch <NAME>",
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
