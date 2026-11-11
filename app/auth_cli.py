"""Manage Macrolog users from the command line.

    python -m app.auth_cli add-user USERNAME [--name NAME] [--email EMAIL]
    python -m app.auth_cli set-password USERNAME
    python -m app.auth_cli set-email USERNAME EMAIL
    python -m app.auth_cli list-users
    python -m app.auth_cli make-admin USERNAME
    python -m app.auth_cli remove-admin USERNAME
    python -m app.auth_cli enable-user USERNAME
    python -m app.auth_cli disable-user USERNAME
    python -m app.auth_cli unset-config KEY      (drop a setting changed in the admin page, e.g. local_login)

Passwords are always read with a no-echo prompt, never from arguments.
Use these to recover when locked out of the admin page. Changes are recorded in the admin log.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from . import admin, auth, config, db


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
    for cmd, text in (("make-admin", "give a user administrator rights"),
                      ("remove-admin", "take administrator rights away (refuses the last admin)"),
                      ("enable-user", "allow a disabled user to sign in again"),
                      ("disable-user", "block a user from signing in and end their sessions")):
        sub.add_parser(cmd, help=text).add_argument("username")
    unset = sub.add_parser("unset-config", help="remove a setting stored from the admin page, so the "
                                                "environment value (or default) applies again")
    unset.add_argument("key", choices=sorted(config.MANAGED))
    return p


def _admin_command(c, args: argparse.Namespace) -> str:
    name = auth.normalize_username(args.username)
    if args.cmd in ("make-admin", "remove-admin"):
        auth.set_admin(c, name, args.cmd == "make-admin")
        done = "is now an administrator" if args.cmd == "make-admin" else "is no longer an administrator"
    else:
        auth.set_disabled(c, name, args.cmd == "disable-user")
        done = "is disabled" if args.cmd == "disable-user" else "is enabled"
    admin.log_action(c, None, "cli." + args.cmd, name)
    return f"'{name}' {done}"


def _unset_config(c, key: str) -> str:
    if key == "oidc_issuer":
        auth.pin_unstamped_identities(c, auth.current_issuer(c))  # links keep the issuer they were made with
    removed = config.unset(c, key)
    admin.log_action(c, None, "cli.unset-config", key)
    if not removed:
        return f"'{key}' was not set in the database; the environment value or default applies"
    return f"Removed '{key}' from the database; the environment value or default applies now"


def _run(args: argparse.Namespace) -> str:
    with db.conn() as c:
        db.init_shared(c)
        auth.init(c)
        admin.init(c)
        if args.cmd == "list-users":
            rows = auth.list_users(c)
            lines = [f"{r['id']}\t{r['username']}\t{r['display_name'] or ''}\t{r['email'] or ''}\t"
                     f"{'password' if r['has_password'] else '-'}\t{'sso' if r['has_oidc'] else '-'}\t"
                     f"{'admin' if r['is_admin'] else '-'}\t{'disabled' if r['disabled'] else '-'}" for r in rows]
            return "\n".join(["id\tusername\tname\temail\tpassword\tsso\tadmin\tdisabled"] + lines)
        if args.cmd in ("make-admin", "remove-admin", "enable-user", "disable-user"):
            return _admin_command(c, args)
        if args.cmd == "unset-config":
            return _unset_config(c, args.key)
        if args.cmd == "set-email":
            auth.set_email(c, args.username, args.email)
            return f"Email updated for '{auth.normalize_username(args.username)}'"
        if args.cmd == "add-user":
            name = auth.validate_username(args.username)
            if auth.find_user(c, name):
                raise ValueError(f"User '{name}' already exists")
            auth.create_user(c, name, _ask_password(), args.name, args.email)
            admin.log_action(c, None, "cli.add-user", name)
            return f"Created user '{name}'"
        if not auth.find_user(c, args.username):
            raise ValueError(f"No user '{auth.normalize_username(args.username)}'")
        auth.set_password(c, args.username, _ask_password())
        admin.log_action(c, None, "cli.set-password", auth.normalize_username(args.username))
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
