"""Manage Macrolog users from the command line.

    python -m app.auth_cli add-user USERNAME [--name NAME] [--email EMAIL]
    python -m app.auth_cli set-password USERNAME
    python -m app.auth_cli set-email USERNAME EMAIL
    python -m app.auth_cli list-users

Passwords are always read with a no-echo prompt, never from arguments.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from . import auth, db


def _ask_password() -> str:
    first = getpass.getpass("Password: ")
    auth.validate_password(first)
    if getpass.getpass("Repeat password: ") != first:
        raise ValueError("Passwords do not match")
    return first


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.auth_cli", description="Manage Macrolog users")
    sub = p.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add-user", help="create a local user (prompts for password)")
    add.add_argument("username")
    add.add_argument("--name", help="display name")
    add.add_argument("--email", help="email, used to link an SSO login with a verified email")
    pw = sub.add_parser("set-password", help="set or reset a user's password (prompts)")
    pw.add_argument("username")
    em = sub.add_parser("set-email", help="set a user's email (empty string clears it)")
    em.add_argument("username")
    em.add_argument("email")
    sub.add_parser("list-users", help="list users")
    return p


def _run(args: argparse.Namespace) -> str:
    with db.conn() as c:
        db.init_shared(c)
        auth.init(c)
        if args.cmd == "list-users":
            rows = auth.list_users(c)
            lines = [f"{r['id']}\t{r['username']}\t{r['display_name'] or ''}\t{r['email'] or ''}\t"
                     f"{'password' if r['has_password'] else '-'}\t{'sso' if r['has_oidc'] else '-'}" for r in rows]
            return "\n".join(["id\tusername\tname\temail\tpassword\tsso"] + lines)
        if args.cmd == "set-email":
            auth.set_email(c, args.username, args.email)
            return f"Email updated for '{auth.normalize_username(args.username)}'"
        if args.cmd == "add-user":
            name = auth.validate_username(args.username)
            if auth.find_user(c, name):
                raise ValueError(f"User '{name}' already exists")
            auth.create_user(c, name, _ask_password(), args.name, args.email)
            return f"Created user '{name}'"
        if not auth.find_user(c, args.username):
            raise ValueError(f"No user '{auth.normalize_username(args.username)}'")
        auth.set_password(c, args.username, _ask_password())
        return f"Password updated for '{auth.normalize_username(args.username)}'"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        message = _run(args)
    except (ValueError, KeyboardInterrupt, EOFError) as exc:
        sys.stderr.write(f"Error: {exc or 'cancelled'}\n")
        return 1
    sys.stdout.write(message + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
