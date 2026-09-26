"""Account administration, from the server's shell.

There is no web route that creates a user. That is deliberate: a first-run web
wizard is a race (two people hitting it at once) and a default account is
something someone forgets to remove. Creating an account requires shell access
to the host, which is the same privilege the app itself runs with.

    python -m app.cli create-user --username alice --role custodian
    python -m app.cli list-users
    python -m app.cli set-password --username alice
    python -m app.cli set-role --username bob --role researcher
    python -m app.cli disable --username bob
    python -m app.cli purge-sessions

Passwords are read with getpass, never from argv - argv is visible in the
process table and lands in shell history.
"""

import argparse
import getpass
import sys

from app.core import auth, passwords, store
from app.core.authz import Role


def _prompt_password(confirm: bool = True) -> str:
    while True:
        first = getpass.getpass("password: ")
        try:
            passwords.validate(first)
        except passwords.PasswordError as e:
            print(f"  {e}", file=sys.stderr)
            continue
        if not confirm:
            return first
        if first != getpass.getpass("confirm: "):
            print("  passwords did not match", file=sys.stderr)
            continue
        return first


def _actor() -> str:
    return f"cli:{getpass.getuser()}"


def create_user(args) -> int:
    if auth.get_user(args.username):
        print(f"user {args.username!r} already exists", file=sys.stderr)
        return 1

    role = Role(args.role)
    # Refuse to make the very first account a researcher: there would be
    # nobody who could create a custodian afterwards without going back to the
    # CLI, and the account could not load the data it exists to analyse.
    if auth.user_count() == 0 and role is not Role.CUSTODIAN:
        print("the first account must be a custodian - otherwise nobody can "
              "load data or create further accounts", file=sys.stderr)
        return 1

    pw = _prompt_password()
    auth.create_user(args.username, passwords.hash_password(pw), role,
                     display_name=args.display_name, created_by=_actor())
    print(f"created {args.username!r} as {role.value}")
    return 0


def set_password(args) -> int:
    if not auth.get_user(args.username):
        print(f"no such user {args.username!r}", file=sys.stderr)
        return 1
    pw = _prompt_password()
    auth.set_password(args.username, passwords.hash_password(pw), by=_actor())
    print(f"password changed for {args.username!r}; their sessions were ended")
    return 0


def set_role(args) -> int:
    user = auth.get_user(args.username)
    if not user:
        print(f"no such user {args.username!r}", file=sys.stderr)
        return 1

    role = Role(args.role)
    if user["role"] == Role.CUSTODIAN.value and role is not Role.CUSTODIAN:
        remaining = [u for u in auth.list_users()
                     if u["role"] == Role.CUSTODIAN.value
                     and not u["disabled"]
                     and u["username"].lower() != args.username.lower()]
        if not remaining:
            print("that is the last active custodian - promote someone else "
                  "first, or the instance becomes unadministrable",
                  file=sys.stderr)
            return 1

    auth.set_role(args.username, role, by=_actor())
    print(f"{args.username!r} is now {role.value}; their sessions were ended")
    return 0


def disable(args) -> int:
    if not auth.get_user(args.username):
        print(f"no such user {args.username!r}", file=sys.stderr)
        return 1
    auth.set_disabled(args.username, not args.enable, by=_actor())
    print(f"{args.username!r} is now {'enabled' if args.enable else 'disabled'}")
    return 0


def list_users(_args) -> int:
    users = auth.list_users()
    if not users:
        print("no accounts yet - create one with: "
              "python -m app.cli create-user --username <you> --role custodian")
        return 0

    print(f"{'username':24} {'role':12} {'state':10} created")
    for u in users:
        state = "disabled" if u["disabled"] else "active"
        print(f"{u['username']:24} {u['role']:12} {state:10} {u['created_at'][:19]}")
    return 0


def purge_sessions(_args) -> int:
    print(f"removed {auth.purge_expired()} expired session(s)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli",
                                     description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="create an account")
    p.add_argument("--username", required=True)
    p.add_argument("--role", required=True, choices=[r.value for r in Role])
    p.add_argument("--display-name")
    p.set_defaults(fn=create_user)

    p = sub.add_parser("set-password", help="change a password and end that user's sessions")
    p.add_argument("--username", required=True)
    p.set_defaults(fn=set_password)

    p = sub.add_parser("set-role", help="change a role and end that user's sessions")
    p.add_argument("--username", required=True)
    p.add_argument("--role", required=True, choices=[r.value for r in Role])
    p.set_defaults(fn=set_role)

    p = sub.add_parser("disable", help="disable (or re-enable) an account")
    p.add_argument("--username", required=True)
    p.add_argument("--enable", action="store_true", help="re-enable instead")
    p.set_defaults(fn=disable)

    p = sub.add_parser("list-users", help="list accounts")
    p.set_defaults(fn=list_users)

    p = sub.add_parser("purge-sessions", help="delete expired sessions")
    p.set_defaults(fn=purge_sessions)

    args = parser.parse_args(argv)
    store.migrate()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
