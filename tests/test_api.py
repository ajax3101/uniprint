from sqlalchemy import select
from sqlalchemy.orm import Session
from xml.etree import ElementTree as ET

from uniprint.auth import Actor, current_actor
from uniprint.models import Cartridge, CartridgeInstallation, CartridgeModel, CartridgeMovement, CartridgeService, Department, Printer, RequestEvent, ServiceRequest


def test_health_is_available_without_identity(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_domain_api_stays_closed_without_identity_provider(client, monkeypatch):
    monkeypatch.delenv("UNIPRINT_AUTH_MODE", raising=False)
    client.app.dependency_overrides.pop(current_actor)
    response = client.get("/api/cartridge-models")
    assert response.status_code == 503


def test_requester_cannot_approve_their_own_request(client, printer_fixture):
    printer, _ = printer_fixture
    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-requester", roles=frozenset({"employee"}))
    response = client.post("/api/requests", json={"printer_id": printer.id, "request_type": "refill"})
    request_id = response.json()["id"]
    client.app.dependency_overrides[current_actor] = lambda: Actor(
        id="test-requester", roles=frozenset({"employee", "approver"})
    )

    assert client.post(f"/api/requests/{request_id}/transitions", json={"target_status": "in_review"}).status_code == 200
    rejected_self_approval = client.post(
        f"/api/requests/{request_id}/transitions", json={"target_status": "approved"}
    )
    assert rejected_self_approval.status_code == 409


def test_employee_cannot_request_printer_outside_department(client, session: Session, printer_fixture):
    printer, _ = printer_fixture
    other_department = Department(name="Other Test Department")
    session.add(other_department)
    session.flush()
    other_printer = Printer(
        asset_number="TEST-PRN-OTHER",
        printer_model_id=printer.printer_model_id,
        department_id=other_department.id,
    )
    session.add(other_printer)
    session.commit()
    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-requester", roles=frozenset({"employee"}))

    response = client.post("/api/requests", json={"printer_id": other_printer.id, "request_type": "refill"})
    assert response.status_code == 403


def test_request_creation_writes_initial_event(client, session: Session, printer_fixture):
    printer, _ = printer_fixture
    response = client.post(
        "/api/requests",
        json={"printer_id": printer.id, "request_type": "refill", "description": "Toner low"},
    )
    assert response.status_code == 201
    request_id = response.json()["id"]
    request = session.get(ServiceRequest, request_id)
    events = list(session.scalars(select(RequestEvent).where(RequestEvent.request_id == request_id)))
    assert request.status == "submitted"
    assert [(event.event_type, event.to_status) for event in events] == [("submitted", "submitted")]


def test_approval_and_issue_are_atomic_and_idempotent(client, session: Session, printer_fixture):
    printer, cartridge_model = printer_fixture
    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-requester", roles=frozenset({"employee"}))
    request_response = client.post("/api/requests", json={"printer_id": printer.id, "request_type": "replacement"})
    request_id = request_response.json()["id"]

    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-approver", roles=frozenset({"approver"}))
    assert client.post(f"/api/requests/{request_id}/transitions", json={"target_status": "in_review"}).status_code == 200
    assert client.post(f"/api/requests/{request_id}/transitions", json={"target_status": "approved"}).status_code == 200

    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-storekeeper", roles=frozenset({"storekeeper"}))
    cartridge = Cartridge(asset_code="CART-TEST-0001", cartridge_model_id=cartridge_model.id)
    session.add(cartridge)
    session.commit()
    payload = {"cartridge_code": cartridge.asset_code, "recipient_id": "synthetic-recipient"}
    headers = {"Idempotency-Key": "issue-test-key-0001"}
    first = client.post(f"/api/requests/{request_id}/issue", json=payload, headers=headers)
    second = client.post(f"/api/requests/{request_id}/issue", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "issued"
    assert len(list(session.scalars(select(CartridgeMovement)))) == 1
    second_cartridge = Cartridge(asset_code="CART-TEST-0002", cartridge_model_id=cartridge_model.id)
    session.add(second_cartridge)
    session.commit()
    duplicate_issue = client.post(
        f"/api/requests/{request_id}/issue",
        json={"cartridge_code": second_cartridge.asset_code, "recipient_id": "synthetic-recipient"},
        headers={"Idempotency-Key": "issue-second-item-01"},
    )
    assert duplicate_issue.status_code == 409
    event_types = list(session.scalars(select(RequestEvent.event_type).where(RequestEvent.request_id == request_id)))
    assert event_types.count("cartridge_issued") == 1


def test_incompatible_cartridge_cannot_be_issued(client, session: Session, printer_fixture):
    printer, _ = printer_fixture
    other_model = CartridgeModel(manufacturer="Other", model_name="Wrong toner")
    session.add(other_model)
    session.flush()
    request = ServiceRequest(
        request_number="UP-TEST000001",
        created_by="test-admin",
        printer_id=printer.id,
        request_type="refill",
        status="approved",
    )
    cartridge = Cartridge(asset_code="CART-TEST-WRONG", cartridge_model=other_model)
    session.add_all([request, cartridge])
    session.commit()

    response = client.post(
        f"/api/requests/{request.id}/issue",
        json={"cartridge_code": cartridge.asset_code, "recipient_id": "synthetic-recipient"},
        headers={"Idempotency-Key": "issue-test-key-wrong"},
    )
    assert response.status_code == 409
    session.refresh(cartridge)
    assert cartridge.status == "in_stock"


def test_receipt_endpoint_records_history_and_replays_idempotently(client, session: Session, printer_fixture):
    _, cartridge_model = printer_fixture
    payload = {"asset_code": "CART-API-0001", "cartridge_model_id": cartridge_model.id}
    headers = {"Idempotency-Key": "receipt-test-key-001"}
    first = client.post("/api/cartridges", json=payload, headers=headers)
    second = client.post("/api/cartridges", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    movement = session.scalar(select(CartridgeMovement).where(CartridgeMovement.idempotency_key == headers["Idempotency-Key"]))
    assert movement.movement_type == "receipt"
    assert movement.request_id is None


def test_qr_label_uses_an_opaque_token_and_requires_stock_role(client, session: Session, printer_fixture):
    _, cartridge_model = printer_fixture
    cartridge = Cartridge(asset_code="CART-LABEL-0001", cartridge_model_id=cartridge_model.id)
    session.add(cartridge)
    session.commit()
    assert cartridge.label_token != cartridge.asset_code

    response = client.get(f"/api/cartridges/{cartridge.asset_code}/label.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["cache-control"] == "private, no-store"
    root = ET.fromstring(response.content)
    assert root.tag.endswith("svg")
    assert any(element.tag.endswith("path") for element in root)
    assert [element.text for element in root if element.tag.endswith("text")] == ["CART-LABEL-0001", "Test Toner 1"]
    assert cartridge.label_token not in response.text

    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-requester", roles=frozenset({"employee"}))
    assert client.get(f"/api/cartridges/{cartridge.asset_code}/label.svg").status_code == 403


def test_return_refill_and_inspection_preserve_cartridge_history(client, session: Session, printer_fixture):
    printer, cartridge_model = printer_fixture
    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-requester", roles=frozenset({"employee"}))
    request_response = client.post("/api/requests", json={"printer_id": printer.id, "request_type": "refill"})
    request_id = request_response.json()["id"]
    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-approver", roles=frozenset({"approver"}))
    client.post(f"/api/requests/{request_id}/transitions", json={"target_status": "in_review"})
    client.post(f"/api/requests/{request_id}/transitions", json={"target_status": "approved"})
    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-storekeeper", roles=frozenset({"storekeeper"}))
    cartridge = Cartridge(asset_code="CART-REFILL-0001", cartridge_model_id=cartridge_model.id)
    session.add(cartridge)
    session.commit()
    issue = client.post(
        f"/api/requests/{request_id}/issue",
        json={"cartridge_code": cartridge.asset_code, "recipient_id": "test-requester"},
        headers={"Idempotency-Key": "issue-refill-key-01"},
    )
    assert issue.status_code == 200

    wrong_recipient_return = client.post(
        f"/api/requests/{request_id}/return",
        json={"cartridge_code": cartridge.asset_code, "recipient_id": "test-admin", "outcome": "stock"},
        headers={"Idempotency-Key": "return-wrong-user-01"},
    )
    assert wrong_recipient_return.status_code == 409

    returned = client.post(
        f"/api/requests/{request_id}/return",
        json={
            "cartridge_code": cartridge.asset_code,
            "recipient_id": "test-requester",
            "outcome": "refill",
            "condition": "Used, intact",
            "counter_reading": 15125,
        },
        headers={"Idempotency-Key": "return-refill-key-01"},
    )
    assert returned.status_code == 200
    assert returned.json()["status"] == "sent_for_refill"
    return_movement = session.scalar(
        select(CartridgeMovement).where(CartridgeMovement.idempotency_key == "return-refill-key-01")
    )
    assert return_movement.counter_reading_source == "manual"
    assert return_movement.counter_reading_recorded_at is not None

    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-admin", roles=frozenset({"admin"}))
    completed = client.post(
        f"/api/cartridges/{cartridge.asset_code}/refill-completion",
        json={"provider": "Synthetic workshop", "cost": "12.50", "currency": "UAH", "test_result": "Test page passed"},
        headers={"Idempotency-Key": "refill-done-key-001"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "pending_inspection"
    assert completed.json()["refill_count"] == 1

    inspected = client.post(
        f"/api/cartridges/{cartridge.asset_code}/inspection",
        json={"result": "stock", "condition": "Ready"},
        headers={"Idempotency-Key": "inspect-stock-key-1"},
    )
    assert inspected.status_code == 200
    assert inspected.json()["status"] == "in_stock"
    service = session.scalar(select(CartridgeService).where(CartridgeService.cartridge_id == cartridge.id))
    assert service.status == "completed"
    assert service.inspection_result == "stock"
    movements = list(session.scalars(select(CartridgeMovement).where(CartridgeMovement.cartridge_id == cartridge.id)))
    assert [movement.movement_type for movement in movements] == ["issue", "return", "refill_return", "inspection"]
    timeline = client.get(f"/api/cartridges/{cartridge.asset_code}/events")
    assert timeline.status_code == 200
    assert [event["movement_type"] for event in timeline.json()] == ["issue", "return", "refill_return", "inspection"]
    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-requester", roles=frozenset({"employee"}))
    assert client.get(f"/api/cartridges/{cartridge.asset_code}/events").status_code == 403


def test_install_remove_and_repair_cycle_is_recorded_and_idempotent(client, session: Session, printer_fixture):
    printer, cartridge_model = printer_fixture
    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-requester", roles=frozenset({"employee"}))
    request_response = client.post("/api/requests", json={"printer_id": printer.id, "request_type": "replacement"})
    request_id = request_response.json()["id"]
    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-approver", roles=frozenset({"approver"}))
    assert client.post(f"/api/requests/{request_id}/transitions", json={"target_status": "in_review"}).status_code == 200
    assert client.post(f"/api/requests/{request_id}/transitions", json={"target_status": "approved"}).status_code == 200
    cartridge = Cartridge(asset_code="CART-INSTALL-0001", cartridge_model_id=cartridge_model.id)
    session.add(cartridge)
    session.commit()
    scanned_qr = f"UPC:{cartridge.label_token}"

    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-storekeeper", roles=frozenset({"storekeeper"}))
    issue = client.post(
        f"/api/requests/{request_id}/issue",
        json={"cartridge_code": scanned_qr, "recipient_id": "test-requester"},
        headers={"Idempotency-Key": "install-cycle-issue-001"},
    )
    assert issue.status_code == 200
    storekeeper_requests = client.get("/api/requests")
    assert storekeeper_requests.status_code == 200
    assert request_id in [row["id"] for row in storekeeper_requests.json()]
    assert client.get(f"/api/requests/{request_id}").status_code == 200
    assert client.post(
        f"/api/requests/{request_id}/transitions", json={"target_status": "fulfilled"}
    ).status_code == 409

    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-requester", roles=frozenset({"employee"}))
    install_headers = {"Idempotency-Key": "install-cycle-install-01"}
    installed = client.post(
        f"/api/requests/{request_id}/install",
        json={"cartridge_code": scanned_qr, "counter_reading": 1500},
        headers=install_headers,
    )
    assert installed.status_code == 200
    assert client.post(
        f"/api/requests/{request_id}/install",
        json={"cartridge_code": scanned_qr, "counter_reading": 1500},
        headers=install_headers,
    ).status_code == 200
    assert installed.json()["status"] == "installed"
    assert client.get(f"/api/cartridges/{cartridge.asset_code}/events").status_code == 403
    assert client.get("/api/installations").status_code == 403

    client.app.dependency_overrides[current_actor] = lambda: Actor(id="test-admin", roles=frozenset({"admin", "storekeeper", "technician"}))
    active_installations = client.get("/api/installations")
    assert active_installations.status_code == 200
    assert [row["cartridge"]["asset_code"] for row in active_installations.json()] == [cartridge.asset_code]
    return_while_installed = client.post(
        f"/api/requests/{request_id}/return",
        json={"cartridge_code": scanned_qr, "recipient_id": "test-requester", "outcome": "repair"},
        headers={"Idempotency-Key": "install-cycle-early-return"},
    )
    assert return_while_installed.status_code == 409
    remove_headers = {"Idempotency-Key": "install-cycle-remove-001"}
    removed = client.post(
        f"/api/requests/{request_id}/remove",
        json={"cartridge_code": scanned_qr, "counter_reading": 7200, "condition": "Faded print"},
        headers=remove_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["status"] == "issued"
    assert client.get("/api/installations").json() == []
    assert client.post(
        f"/api/requests/{request_id}/remove",
        json={"cartridge_code": scanned_qr, "counter_reading": 7200, "condition": "Faded print"},
        headers=remove_headers,
    ).status_code == 200
    active_installation = session.scalar(
        select(CartridgeInstallation).where(CartridgeInstallation.cartridge_id == cartridge.id, CartridgeInstallation.removed_at.is_(None))
    )
    assert active_installation is None
    installation = session.scalar(select(CartridgeInstallation).where(CartridgeInstallation.cartridge_id == cartridge.id))
    assert installation.install_counter == 1500
    assert installation.remove_counter == 7200
    assert installation.install_counter_source == "manual"
    assert installation.install_counter_recorded_at is not None
    assert installation.remove_counter_source == "manual"
    assert installation.remove_counter_recorded_at is not None
    install_movement = session.scalar(
        select(CartridgeMovement).where(CartridgeMovement.idempotency_key == install_headers["Idempotency-Key"])
    )
    assert install_movement.counter_reading_source == "manual"
    assert install_movement.counter_reading_recorded_at is not None

    returned = client.post(
        f"/api/requests/{request_id}/return",
        json={"cartridge_code": scanned_qr, "recipient_id": "test-requester", "outcome": "repair"},
        headers={"Idempotency-Key": "install-cycle-return-001"},
    )
    assert returned.status_code == 200
    assert returned.json()["status"] == "in_repair"
    completed = client.post(
        f"/api/cartridges/{scanned_qr}/repair-completion",
        json={"provider": "Synthetic repair shop", "test_result": "Test page passed"},
        headers={"Idempotency-Key": "install-cycle-repair-done"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "pending_inspection"
    inspected = client.post(
        f"/api/cartridges/{scanned_qr}/inspection",
        json={"result": "stock", "condition": "Ready"},
        headers={"Idempotency-Key": "install-cycle-inspection"},
    )
    assert inspected.status_code == 200
    assert inspected.json()["status"] == "in_stock"
    movement_types = list(
        session.scalars(
            select(CartridgeMovement.movement_type)
            .where(CartridgeMovement.cartridge_id == cartridge.id)
            .order_by(CartridgeMovement.created_at, CartridgeMovement.id)
        )
    )
    assert movement_types == ["issue", "install", "remove", "return", "repair_return", "inspection"]
    repair_service = session.scalar(
        select(CartridgeService).where(CartridgeService.cartridge_id == cartridge.id, CartridgeService.service_type == "repair")
    )
    assert repair_service is not None
    assert repair_service.status == "completed"
