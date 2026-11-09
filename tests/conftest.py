from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from uniprint.api import app
from uniprint.auth import Actor, current_actor
from uniprint.database import Base, get_session
from uniprint.models import CartridgeModel, Department, Printer, PrinterModel, User


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(session: Session) -> Generator[TestClient, None, None]:
    def override_session() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[current_actor] = lambda: Actor(id="test-admin", roles=frozenset({"admin", "employee", "approver", "technician", "storekeeper"}))
    department = Department(name="Test Department")
    session.add(department)
    session.flush()
    session.add_all(
        [
            User(id="test-admin", display_name="Synthetic test administrator"),
            User(id="test-requester", display_name="Synthetic test requester", department_id=department.id),
            User(id="test-approver", display_name="Synthetic test approver", department_id=department.id),
            User(id="test-storekeeper", display_name="Synthetic test storekeeper"),
        ]
    )
    session.commit()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def printer_fixture(session: Session) -> tuple[Printer, CartridgeModel]:
    department = session.scalar(select(Department).where(Department.name == "Test Department"))
    assert department is not None
    recipient = User(id="synthetic-recipient", display_name="Synthetic recipient", department_id=department.id)
    printer_model = PrinterModel(manufacturer="Test", model_name="Laser 1")
    cartridge_model = CartridgeModel(manufacturer="Test", model_name="Toner 1")
    printer_model.cartridge_models.append(cartridge_model)
    printer = Printer(asset_number="TEST-PRN-1", printer_model=printer_model, department_id=department.id)
    session.add_all([department, recipient, printer_model, cartridge_model, printer])
    session.commit()
    return printer, cartridge_model
