#!/usr/bin/env python3
"""
Foodies Management CLI
Commands:
  python manage.py migrate       - Initialize and upgrade database tables idempotently
  python manage.py create-admin   - Create an admin user (prompts with getpass, min 10 chars)
  python manage.py seed-demo      - Seed demo accounts (disabled in production)
  python manage.py test           - Execute the automated test suite
"""

import sys
import os
import argparse
import getpass

# Ensure project root is in sys.path
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import (
    init_db,
    seed_demo_accounts,
    create_admin_user,
    run_self_tests,
    APP_ENV,
    DB_PATH
)


def cmd_migrate(args):
    print(f"Running database migrations on: {DB_PATH} (APP_ENV={APP_ENV})")
    init_db(seed_demo=False)
    print("Schema initialization and migrations applied successfully.")
    return 0


def cmd_create_admin(args):
    email = args.email
    password = args.password
    name = args.name or "Administrator"

    if not email:
        try:
            email = input("Admin Email: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return 1

    if not email or "@" not in email:
        print("Error: A valid email address is required.", file=sys.stderr)
        return 1

    if not password:
        try:
            password = getpass.getpass("Admin Password (min 10 characters): ")
            password_confirm = getpass.getpass("Confirm Admin Password: ")
            if password != password_confirm:
                print("Error: Passwords do not match.", file=sys.stderr)
                return 1
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return 1

    if len(password) < 10:
        print(f"Error: Password must be at least 10 characters long (received {len(password)}).", file=sys.stderr)
        return 1

    try:
        user_id = create_admin_user(email=email, password=password, name=name)
        print(f"Admin user '{email}' created successfully (ID: {user_id}).")
        return 0
    except Exception as e:
        print(f"Error creating admin user: {e}", file=sys.stderr)
        return 1


def cmd_seed_demo(args):
    if APP_ENV == "production" and not args.force:
        print("Error: Demo accounts cannot be seeded when APP_ENV=production.", file=sys.stderr)
        print("Never seed demo accounts (admin@foodies.com, etc.) in production environments.", file=sys.stderr)
        return 1

    success = seed_demo_accounts()
    if success:
        print("Demo accounts seeded successfully:")
        print("  - admin@foodies.com      (role: admin)")
        print("  - moderator@foodies.com  (role: moderator)")
        print("  - user@foodies.com       (role: user)")
        return 0
    else:
        print("Failed to seed demo accounts (refused in production).", file=sys.stderr)
        return 1


def cmd_test(args):
    return run_self_tests()


def main():
    parser = argparse.ArgumentParser(description="Foodies Cloud Management CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # migrate
    subparsers.add_parser("migrate", help="Run database migrations idempotently")

    # create-admin
    parser_admin = subparsers.add_parser("create-admin", help="Create an administrator account")
    parser_admin.add_argument("--email", help="Admin email address", default=None)
    parser_admin.add_argument("--password", help="Admin password (min 10 characters)", default=None)
    parser_admin.add_argument("--name", help="Admin full name", default="Administrator")

    # seed-demo
    parser_seed = subparsers.add_parser("seed-demo", help="Seed demo accounts (development/test only)")
    parser_seed.add_argument("--force", action="store_true", help="Force seeding even if in production (DANGEROUS)")

    # test
    subparsers.add_parser("test", help="Execute automated test suite")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    handlers = {
        "migrate": cmd_migrate,
        "create-admin": cmd_create_admin,
        "seed-demo": cmd_seed_demo,
        "test": cmd_test,
    }

    handler = handlers.get(args.command)
    if not handler:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
