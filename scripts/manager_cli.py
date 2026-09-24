from __future__ import annotations

import argparse
import getpass
import secrets
import string
import sys
from pathlib import Path
from uuid import UUID

# Allow direct execution:
# python .\scripts\manager_cli.py ...
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import User


DEFAULT_MANAGER_ID = UUID(
    "0a210e24-a1fe-4345-a27e-bd5897ceb889"
)

DEFAULT_MANAGER_EMAIL = "manager@transaction.local"
DEFAULT_MANAGER_NAME = "Bank Manager"


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(
        secrets.choice(alphabet)
        for _ in range(length)
    )


def create_manager() -> None:
    with SessionLocal() as db:
        existing = db.scalar(
            select(User).where(
                User.email == DEFAULT_MANAGER_EMAIL
            )
        )

        if existing is not None:
            if existing.role == "admin":
                print("Manager already exists.")
                print(f"Manager ID : {existing.id}")
                print(f"Email      : {existing.email}")
                print(f"Role       : {existing.role}")
                print()
                print(
                    "Use -update_manager_password to change "
                    "the manager password."
                )
                return

            raise SystemExit(
                f"{DEFAULT_MANAGER_EMAIL} already exists "
                f"with role={existing.role}. "
                "Refusing to promote it automatically."
            )

        existing_id = db.get(
            User,
            DEFAULT_MANAGER_ID,
        )

        if existing_id is not None:
            raise SystemExit(
                "Configured manager ID is already assigned "
                f"to {existing_id.email}."
            )

        password = generate_password()

        manager = User(
            id=DEFAULT_MANAGER_ID,
            name=DEFAULT_MANAGER_NAME,
            email=DEFAULT_MANAGER_EMAIL,
            password_hash=hash_password(password),
            role="admin",
        )

        db.add(manager)
        db.commit()

        print()
        print("Manager created successfully.")
        print("--------------------------------")
        print(f"Manager ID : {manager.id}")
        print(f"Name       : {manager.name}")
        print(f"Email      : {manager.email}")
        print(f"Role       : {manager.role}")
        print(f"Password   : {password}")
        print()
        print(
            "IMPORTANT: save this password now. "
            "It will not be displayed by -know_manager_id."
        )


def update_manager_password() -> None:
    with SessionLocal() as db:
        manager = db.scalar(
            select(User).where(
                User.email == DEFAULT_MANAGER_EMAIL,
                User.role == "admin",
            )
        )

        if manager is None:
            raise SystemExit(
                "Manager account does not exist. "
                "Run -create_manager first."
            )

        first = getpass.getpass(
            "Enter new manager password: "
        )

        second = getpass.getpass(
            "Confirm new manager password: "
        )

        if first != second:
            raise SystemExit(
                "Passwords do not match."
            )

        if len(first) < 8:
            raise SystemExit(
                "Password must contain at least 8 characters."
            )

        manager.password_hash = hash_password(first)

        db.commit()

        print()
        print(
            f"Manager password updated for "
            f"{manager.email}."
        )


def know_manager_id() -> None:
    with SessionLocal() as db:
        manager = db.scalar(
            select(User).where(
                User.email == DEFAULT_MANAGER_EMAIL,
                User.role == "admin",
            )
        )

        if manager is None:
            raise SystemExit(
                "Manager account does not exist."
            )

        print()
        print("Manager account")
        print("-----------------------------")
        print(f"Manager ID : {manager.id}")
        print(f"Name       : {manager.name}")
        print(f"Email      : {manager.email}")
        print(f"Role       : {manager.role}")
        print()
        print(
            "Password is intentionally not displayed."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CLI-only manager administration."
    )

    group = parser.add_mutually_exclusive_group(
        required=True
    )

    group.add_argument(
        "-create_manager",
        action="store_true",
        help="Create the initial manager account.",
    )

    group.add_argument(
        "-update_manager_password",
        action="store_true",
        help="Change the manager password.",
    )

    group.add_argument(
        "-know_manager_id",
        action="store_true",
        help="Show manager identity information.",
    )

    args = parser.parse_args()

    if args.create_manager:
        create_manager()

    elif args.update_manager_password:
        update_manager_password()

    elif args.know_manager_id:
        know_manager_id()


if __name__ == "__main__":
    main()

