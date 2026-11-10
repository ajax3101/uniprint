"""PostgreSQL-only race tests for inventory operations.

These tests intentionally reset a database named `uniprint_test` on loopback.
They remain skipped in normal local and CI runs unless an explicit test URL is
provided.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from uniprint.api import app
from uniprint.auth import Actor, current_actor
from uniprint.database import Base, get_session
from uniprint.models import (
    Cartridge,
    CartridgeInstallation,
    CartridgeModel,
    CartridgeMovement,
    Department,
    Printer,
    PrinterModel,
    ServiceRequest,
    User,
)


ROOT = Path(__file__).resolve().parents[1]


def _test_database_url() -> str:
    database_url = os.environ.get("UNIPRINT_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set UNIPRINT_TEST_DATABASE_URL to run isolated PostgreSQL concurrency tests")

    parsed = make_url(database_url)
    if (
        parsed.drivername not in {"postgresql", "postgresql+psycopg"}
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
        or parsed.database != "uniprint_test"
    ):
        pytest.fail("Concurrency tests only accept a loopback PostgreSQL database named uniprint_test")
    return database_url


@pytest.fixture
def pg_client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    database_url = _test_database_url()
    engine = create_engine(database_url, pool_pre_ping=True)

    # The URL guard above confines destructive schema setup to the disposable
    # test database. Rebuild it from migrations so these tests exercise the
    # schema actually shipped by the repository.
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")

    previous_database_url = os.environ.get("UNIPRINT_DATABASE_URL")
    os.environ["UNIPRINT_DATABASE_URL"] = database_url
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")

    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def override_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[current_actor] = lambda: Actor(
        id="test-storekeeper", roles=frozenset({"admin", "employee", "storekeeper", "technician"})
    )
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("UNIPRINT_DATABASE_URL", None)
        else:
            os.environ["UNIPRINT_DATABASE_URL"] = previous_database_url


def _seed_request(session: Session, *, request_number: str, status: str) -> tuple[ServiceRequest, Cartridge, User]:
    department = Department(name="Concurrency Test Department")
    session.add(department)
    session.flush()
    requester = User(
        id="test-requester", display_name="Synthetic test requester", department_id=department.id
    )
    storekeeper = User(id="test-storekeeper", display_name="Synthetic test storekeeper")
    printer_model = PrinterModel(manufacturer="Test", model_name="Concurrency Printer")
    cartridge_model = CartridgeModel(manufacturer="Test", model_name="Concurrency Toner")
    printer_model.cartridge_models.append(cartridge_model)
    printer = Printer(
        asset_number=f"TEST-{request_number}",
        printer_model=printer_model,
        department_id=department.id,
    )
    request = ServiceRequest(
        request_number=request_number,
        created_by=requester.id,
        department_id=department.id,
        printer=printer,
        request_type="replacement",
        status=status,
    )
    cartridge = Cartridge(asset_code=f"CART-{request_number}", cartridge_model=cartridge_model)
    session.add_all([department, requester, storekeeper, printer_model, cartridge_model, printer, request, cartridge])
    session.commit()
    return request, cartridge, requester


def _parallel_posts(client: TestClient, calls: list[tuple[str, dict[str, Any], dict[str, str]]]):
    barrier = Barrier(len(calls))

    def post(call: tuple[str, dict[str, Any], dict[str, str]]) -> int:
        url, payload, headers = call
        barrier.wait(timeout=10)
        return client.post(url, json=payload, headers=headers).status_code

    with ThreadPoolExecutor(max_workers=len(calls)) as executor:
        return list(executor.map(post, calls))


def test_concurrent_issues_cannot_issue_one_cartridge_twice(pg_client):
    client, factory = pg_client
    with factory() as session:
        request_a, cartridge, requester = _seed_request(session, request_number="UP-CONCUR0001", status="approved")
        request_b = ServiceRequest(
            request_number="UP-CONCUR0002",
            created_by=requester.id,
            department_id=request_a.department_id,
            printer_id=request_a.printer_id,
            request_type="replacement",
            status="approved",
        )
        session.add(request_b)
        session.commit()
        calls = [
            (
                f"/api/requests/{request_id}/issue",
                {"cartridge_code": cartridge.asset_code, "recipient_id": requester.id},
                {"Idempotency-Key": key},
            )
            for request_id, key in (
                (request_a.id, "issue-concurrency-a-01"),
                (request_b.id, "issue-concurrency-b-01"),
            )
        ]

    assert sorted(_parallel_posts(client, calls)) == [200, 409]

    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(CartridgeMovement).where(CartridgeMovement.movement_type == "issue")
        ) == 1
        assert session.get(Cartridge, cartridge.id).status == "issued"
        assert sorted(session.scalars(select(ServiceRequest.status)).all()) == ["approved", "processing"]


def test_concurrent_install_cannot_create_two_active_installations(pg_client):
    client, factory = pg_client
    with factory() as session:
        request, cartridge, requester = _seed_request(session, request_number="UP-CONCUR0003", status="processing")
        cartridge.status = "issued"
        session.add(
            CartridgeMovement(
                cartridge_id=cartridge.id,
                request_id=request.id,
                actor_id="test-storekeeper",
                movement_type="issue",
                to_user_id=requester.id,
                from_status="in_stock",
                to_status="issued",
                idempotency_key="seed-issue-concurrency-01",
            )
        )
        session.commit()
        client.app.dependency_overrides[current_actor] = lambda: Actor(
            id=requester.id, roles=frozenset({"employee"})
        )
        calls = [
            (
                f"/api/requests/{request.id}/install",
                {"cartridge_code": cartridge.asset_code, "counter_reading": 1000},
                {"Idempotency-Key": key},
            )
            for key in ("install-concurrency-a-01", "install-concurrency-b-01")
        ]

    assert sorted(_parallel_posts(client, calls)) == [200, 409]

    with factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(CartridgeInstallation)
            .where(CartridgeInstallation.removed_at.is_(None))
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(CartridgeMovement).where(CartridgeMovement.movement_type == "install")
        ) == 1
        assert session.get(Cartridge, cartridge.id).status == "installed"
