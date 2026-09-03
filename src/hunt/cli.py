from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import HuntError, cards, vault
from .cards import CardError
from .config import load_config
from .validate import validate_parent_dir, validate_vault
from .vault import VaultError


def _category(value):
    try:
        return cards.resolve_category(value)
    except CardError:
        names = sorted(cards.CATEGORIES.values()) + sorted(cards.CATEGORIES)
        raise argparse.ArgumentTypeError(
            "invalid category %r (expected one of: %s)" % (value, ", ".join(names))
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


def cmd_init(args, today):
    config = load_config()
    vault.init(config.vault_path, config.vault_branch)
    print("initialized %s on %s" % (config.vault_path, config.vault_branch))
    return 0


def cmd_new(args, today):
    config = load_config()
    vault.ensure_writable(config)
    number = cards.next_parent_number(config.vault_path, args.category)
    parent_id = cards.parent_id(args.category, number)
    parent = cards.new_parent(parent_id, args.name)
    path = _write(
        config,
        cards.parent_path(config.vault_path, parent_id),
        cards.render_parent(parent, []),
    )
    vault.commit(config.vault_path, [path], "hunt: new %s" % parent_id)
    print(parent_id)
    return 0


def cmd_run(args, today):
    config = load_config()
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
    run = cards.new_run(run_ident, args.date or today.isoformat(), previous)
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
    config = load_config()
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


def build_parser():
    parser = argparse.ArgumentParser(
        prog="hunt",
        description="Create and validate recurring task cards in the vault.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    init = subparsers.add_parser("init", help="initialize the vault repository and branch")
    init.set_defaults(func=cmd_init)

    new = subparsers.add_parser("new", help="create a parent card")
    new.add_argument(
        "--category",
        required=True,
        type=_category,
        metavar="<category>",
        help="baseline, hunt, math, or the code BSL, HNT, MTH",
    )
    new.add_argument(
        "--name", required=True, type=_task_name, metavar="<task name>", help="task name"
    )
    new.set_defaults(func=cmd_new)

    run = subparsers.add_parser("run", help="create the next run card for a parent")
    run.add_argument(
        "--id", required=True, type=_parent_id, metavar="<PARENT-ID>", help="parent id"
    )
    run.add_argument(
        "--date",
        type=_run_date,
        metavar="YYYY-MM-DD",
        help="run date; defaults to today",
    )
    run.set_defaults(func=cmd_run)

    validate = subparsers.add_parser("validate", help="validate the vault")
    validate.add_argument(
        "--id", type=_card_id, metavar="<ID>", help="restrict findings to one card"
    )
    validate.set_defaults(func=cmd_validate)

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
    except HuntError as exc:
        print("hunt: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
