from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import select

from .database import SessionLocal
from .models import Department, User


def create_dev_user(user_id: str, display_name: str, department_name: str | None) -> None:
    if os.environ.get("UNIPRINT_AUTH_MODE") != "development":
        raise SystemExit("Set UNIPRINT_AUTH_MODE=development to use local development tools")
    with SessionLocal() as session:
        department = None
        if department_name:
            department = session.scalar(select(Department).where(Department.name == department_name))
            if department is None:
                department = Department(name=department_name)
                session.add(department)
                session.flush()
        existing = session.get(User, user_id)
        if existing is None:
            session.add(
                User(
                    id=user_id,
                    display_name=display_name,
                    department_id=department.id if department else None,
                )
            )
        else:
            existing.display_name = display_name
            existing.department_id = department.id if department else None
            existing.active = True
        session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a local-only UniPrint development user")
    parser.add_argument("--id", required=True, help="Synthetic development ID, not a real personal identifier")
    parser.add_argument("--name", required=True, help="Synthetic display name")
    parser.add_argument("--department")
    args = parser.parse_args()
    try:
        create_dev_user(args.id, args.name, args.department)
    except Exception as exc:
        print(f"Could not create development user: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Development user {args.id!r} is ready")
