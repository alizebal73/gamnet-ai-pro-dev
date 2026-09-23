"""Server admin CLI.

Create the first owner account (run once after install):

    python -m gamenet.server.cli create-admin --username admin
"""

import argparse
import getpass
import sqlite3
import sys

from gamenet.server.db import get_connection, run_migrations
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.user_service import UserService
from gamenet.shared.enums import RoleName


def cmd_create_admin(args: argparse.Namespace) -> int:
    run_migrations()
    password = getpass.getpass("Password (min 8 chars): ")
    confirm = getpass.getpass("Repeat password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    try:
        with get_connection() as conn:
            user = UserService(conn).create_user(
                username=args.username,
                password=password,
                display_name=args.display_name,
                roles=[RoleName.OWNER.value],
            )
            log_audit(
                conn, action="USER_CREATE", user_id=user["id"],
                entity_type="user", entity_id=user["id"],
                new_value="owner", reason="bootstrap via CLI",
            )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except sqlite3.IntegrityError:
        print(f"Error: username '{args.username}' already exists.", file=sys.stderr)
        return 1
    print(f"Owner account '{user['username']}' created (id={user['id']}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gamenet.server.cli", description="GameNet Pro server admin CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_admin = sub.add_parser("create-admin", help="Create an owner account")
    p_admin.add_argument("--username", required=True)
    p_admin.add_argument("--display-name", default=None)
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return cmd_create_admin(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
