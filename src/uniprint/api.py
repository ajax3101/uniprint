from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import Response as RawResponse
from fastapi.staticfiles import StaticFiles
import qrcode
from qrcode.image.svg import SvgPathImage
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .auth import Actor, current_actor, require_role
from .database import get_session
from .models import (
    Cartridge,
    CartridgeInstallation,
    CartridgeModel,
    CartridgeMovement,
    CartridgeService,
    Printer,
    PrinterModel,
    RequestEvent,
    ServiceRequest,
    User,
)
from .schemas import (
    CartridgeCreate,
    CartridgeModelCreate,
    CartridgeModelRead,
    CartridgeRead,
    IssueCartridge,
    InstallCartridge,
    PrinterCreate,
    PrinterModelCreate,
    PrinterModelRead,
    PrinterRead,
    RequestCreate,
    RequestEventRead,
    RequestRead,
    RequestTransition,
    RemoveCartridge,
    ReturnCartridge,
    RefillCompletion,
    RepairCompletion,
    CartridgeInspection,
    CartridgeInstallationRead,
    CartridgeMovementRead,
)

app = FastAPI(title="UniPrint API", version="0.1.0")
api = APIRouter(prefix="/api")

REQUEST_TRANSITIONS = {
    "submitted": {"in_review", "cancelled"},
    "in_review": {"approved", "rejected", "cancelled"},
    "approved": {"processing", "cancelled"},
    "processing": {"fulfilled", "cancelled"},
    "fulfilled": {"completed"},
}
QR_NAMESPACE = "http://www.w3.org/2000/svg"
ET.register_namespace("", QR_NAMESPACE)


def find_cartridge(session: Session, supplied_code: str, *, for_update: bool = False) -> Cartridge | None:
    value = supplied_code.strip()
    if value.startswith("UPC:"):
        statement = select(Cartridge).where(Cartridge.label_token == value.removeprefix("UPC:"))
    else:
        statement = select(Cartridge).where(or_(Cartridge.asset_code == value, Cartridge.label_token == value))
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def cartridge_matches_code(cartridge: Cartridge, supplied_code: str) -> bool:
    value = supplied_code.strip()
    if value.startswith("UPC:"):
        return cartridge.label_token == value.removeprefix("UPC:")
    return cartridge.asset_code == value or cartridge.label_token == value


def cartridge_label_svg(cartridge: Cartridge) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(f"UPC:{cartridge.label_token}")
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    buffer = BytesIO()
    image.save(buffer)
    root = ET.fromstring(buffer.getvalue())
    width, height = (float(value) for value in root.attrib["viewBox"].split()[2:])
    root.set("height", f"{height + 14:.1f}mm")
    root.set("viewBox", f"0 0 {width:.1f} {height + 14:.1f}")
    model_text = f"{cartridge.cartridge_model.manufacturer} {cartridge.cartridge_model.model_name}"
    for content, y, font_size in ((cartridge.asset_code, height + 5, "3.5"), (model_text, height + 10, "2.5")):
        element = ET.SubElement(root, f"{{{QR_NAMESPACE}}}text", {
            "x": f"{width / 2:.1f}",
            "y": f"{y:.1f}",
            "text-anchor": "middle",
            "font-family": "sans-serif",
            "font-size": f"{font_size}mm",
            "textLength": f"{max(width - 3, 1):.1f}",
            "lengthAdjust": "spacingAndGlyphs",
            "fill": "#111111",
        })
        element.text = content
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api.post("/cartridge-models", response_model=CartridgeModelRead, status_code=status.HTTP_201_CREATED)
def create_cartridge_model(
    payload: CartridgeModelCreate,
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> CartridgeModel:
    require_role(actor, "admin", "technician")
    model = CartridgeModel(**payload.model_dump())
    session.add(model)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Cartridge model already exists") from exc
    session.refresh(model)
    return model


@api.get("/cartridge-models", response_model=list[CartridgeModelRead])
def list_cartridge_models(
    session: Session = Depends(get_session), actor: Actor = Depends(current_actor)
) -> list[CartridgeModel]:
    return list(session.scalars(select(CartridgeModel).order_by(CartridgeModel.manufacturer, CartridgeModel.model_name)))


@api.post("/printer-models", response_model=PrinterModelRead, status_code=status.HTTP_201_CREATED)
def create_printer_model(
    payload: PrinterModelCreate,
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> PrinterModel:
    require_role(actor, "admin", "technician")
    cartridge_models = list(
        session.scalars(select(CartridgeModel).where(CartridgeModel.id.in_(payload.compatible_cartridge_model_ids)))
    )
    if len(cartridge_models) != len(set(payload.compatible_cartridge_model_ids)):
        raise HTTPException(status_code=404, detail="One or more compatible cartridge models were not found")
    model = PrinterModel(manufacturer=payload.manufacturer, model_name=payload.model_name, cartridge_models=cartridge_models)
    session.add(model)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Printer model already exists") from exc
    session.refresh(model)
    return model


@api.post("/printers", response_model=PrinterRead, status_code=status.HTTP_201_CREATED)
def create_printer(
    payload: PrinterCreate,
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> Printer:
    require_role(actor, "admin", "technician")
    if session.get(PrinterModel, payload.printer_model_id) is None:
        raise HTTPException(status_code=404, detail="Printer model not found")
    printer = Printer(**payload.model_dump())
    session.add(printer)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Printer asset number already exists") from exc
    session.refresh(printer)
    return printer


@api.get("/printers", response_model=list[PrinterRead])
def list_printers(
    session: Session = Depends(get_session), actor: Actor = Depends(current_actor)
) -> list[Printer]:
    query = select(Printer).where(Printer.active.is_(True))
    if not actor.roles.intersection({"admin", "technician"}):
        user = session.get(User, actor.id)
        if user is None or user.department_id is None:
            return []
        query = query.where(Printer.department_id == user.department_id)
    return list(session.scalars(query.order_by(Printer.asset_number)))


@api.post("/cartridges", response_model=CartridgeRead, status_code=status.HTTP_201_CREATED)
def create_cartridge(
    payload: CartridgeCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> Cartridge:
    require_role(actor, "admin", "storekeeper")
    if session.get(CartridgeModel, payload.cartridge_model_id) is None:
        raise HTTPException(status_code=404, detail="Cartridge model not found")
    prior = session.scalar(select(CartridgeMovement).where(CartridgeMovement.idempotency_key == idempotency_key))
    if prior is not None:
        if prior.movement_type != "receipt" or prior.cartridge.asset_code != payload.asset_code:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different operation")
        return prior.cartridge
    cartridge = Cartridge(**payload.model_dump())
    session.add(cartridge)
    try:
        session.flush()
        session.add(
            CartridgeMovement(
                cartridge_id=cartridge.id,
                actor_id=actor.id,
                movement_type="receipt",
                idempotency_key=idempotency_key,
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Cartridge code already exists") from exc
    session.refresh(cartridge)
    return cartridge


@api.post("/requests", response_model=RequestRead, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: RequestCreate,
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> ServiceRequest:
    printer = session.get(Printer, payload.printer_id)
    if printer is None or not printer.active:
        raise HTTPException(status_code=404, detail="Printer not found")
    user = session.get(User, actor.id)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="User is unknown or inactive")
    if "admin" not in actor.roles and "technician" not in actor.roles:
        if user.department_id is None or printer.department_id != user.department_id:
            raise HTTPException(status_code=403, detail="Printer is outside the user's department scope")
    request = ServiceRequest(
        request_number=f"UP-{uuid4().hex.upper()}",
        created_by=user.id,
        department_id=user.department_id,
        printer_id=payload.printer_id,
        request_type=payload.request_type,
        description=payload.description,
        status="submitted",
    )
    session.add(request)
    session.flush()
    session.add(
        RequestEvent(
            request_id=request.id,
            actor_id=actor.id,
            event_type="submitted",
            from_status=None,
            to_status="submitted",
        )
    )
    session.commit()
    session.refresh(request)
    return request


@api.get("/requests", response_model=list[RequestRead])
def list_requests(
    session: Session = Depends(get_session), actor: Actor = Depends(current_actor)
) -> list[ServiceRequest]:
    query = select(ServiceRequest).order_by(ServiceRequest.created_at.desc())
    if "storekeeper" in actor.roles and not actor.roles.intersection({"admin", "technician"}):
        query = query.where(ServiceRequest.status.in_(["approved", "processing", "fulfilled"]))
    elif "approver" in actor.roles and not actor.roles.intersection({"admin", "technician"}):
        user = session.get(User, actor.id)
        if user is None or user.department_id is None:
            return []
        query = query.where(ServiceRequest.department_id == user.department_id)
    elif not actor.roles.intersection({"admin", "technician"}):
        query = query.where(ServiceRequest.created_by == actor.id)
    return list(session.scalars(query.limit(200)))


@api.get("/cartridges", response_model=list[CartridgeRead])
def list_cartridges(
    session: Session = Depends(get_session), actor: Actor = Depends(current_actor)
) -> list[Cartridge]:
    query = select(Cartridge).options(selectinload(Cartridge.cartridge_model)).order_by(Cartridge.asset_code).limit(500)
    return list(session.scalars(query))


@api.get("/cartridges/{asset_code}/label.svg")
def get_cartridge_label(
    asset_code: str,
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> RawResponse:
    require_role(actor, "storekeeper", "admin")
    cartridge = find_cartridge(session, asset_code)
    if cartridge is None:
        raise HTTPException(status_code=404, detail="Cartridge not found")
    return RawResponse(
        content=cartridge_label_svg(cartridge),
        media_type="image/svg+xml",
        headers={"Cache-Control": "private, no-store"},
    )


@api.get("/cartridges/{asset_code}/events", response_model=list[CartridgeMovementRead])
def list_cartridge_events(
    asset_code: str,
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> list[CartridgeMovement]:
    require_role(actor, "storekeeper", "technician", "admin")
    cartridge = find_cartridge(session, asset_code)
    if cartridge is None:
        raise HTTPException(status_code=404, detail="Cartridge not found")
    return list(
        session.scalars(
            select(CartridgeMovement)
            .where(CartridgeMovement.cartridge_id == cartridge.id)
            .order_by(CartridgeMovement.created_at, CartridgeMovement.id)
        )
    )


@api.get("/installations", response_model=list[CartridgeInstallationRead])
def list_installations(
    active_only: bool = True,
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> list[CartridgeInstallation]:
    require_role(actor, "storekeeper", "technician", "admin")
    query = select(CartridgeInstallation).options(
        selectinload(CartridgeInstallation.cartridge).selectinload(Cartridge.cartridge_model),
        selectinload(CartridgeInstallation.printer),
    )
    if active_only:
        query = query.where(CartridgeInstallation.removed_at.is_(None))
    return list(session.scalars(query.order_by(CartridgeInstallation.installed_at.desc())).unique())


@api.get("/requests/{request_id}", response_model=RequestRead)
def get_request(
    request_id: str,
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> ServiceRequest:
    request = session.get(ServiceRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if "admin" in actor.roles or "technician" in actor.roles:
        return request
    if "storekeeper" in actor.roles and request.status in {"approved", "processing", "fulfilled"}:
        return request
    if "approver" in actor.roles:
        user = session.get(User, actor.id)
        if user is not None and user.department_id is not None and request.department_id == user.department_id:
            return request
        raise HTTPException(status_code=403, detail="Request is outside actor department scope")
    if request.created_by != actor.id:
        raise HTTPException(status_code=403, detail="Request is outside actor scope")
    return request


@api.get("/requests/{request_id}/events", response_model=list[RequestEventRead])
def list_request_events(
    request_id: str,
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> list[RequestEvent]:
    request = get_request(request_id, session, actor)
    return list(session.scalars(select(RequestEvent).where(RequestEvent.request_id == request.id).order_by(RequestEvent.created_at)))


@api.post("/requests/{request_id}/transitions", response_model=RequestRead)
def transition_request(
    request_id: str,
    payload: RequestTransition,
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> ServiceRequest:
    request = session.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    target = payload.target_status
    if target not in REQUEST_TRANSITIONS.get(request.status, set()):
        raise HTTPException(status_code=409, detail=f"Transition {request.status} -> {target} is not allowed")
    required_role = {
        "in_review": ("approver", "technician", "admin"),
        "approved": ("approver", "admin"),
        "rejected": ("approver", "admin"),
        "processing": ("technician", "admin"),
        "fulfilled": ("technician", "storekeeper", "admin"),
        "completed": ("employee", "admin"),
        "cancelled": ("employee", "approver", "technician", "admin"),
    }[target]
    require_role(actor, *required_role)
    if target in {"approved", "rejected"} and request.created_by == actor.id:
        raise HTTPException(status_code=409, detail="A requester cannot approve or reject their own request")
    if target in {"completed", "cancelled"} and request.created_by != actor.id and "admin" not in actor.roles:
        raise HTTPException(status_code=403, detail="Only the requester or an administrator may close this request")
    if target == "fulfilled":
        issued_cartridges = list(
            session.scalars(
                select(Cartridge)
                .join(CartridgeMovement, CartridgeMovement.cartridge_id == Cartridge.id)
                .where(
                    CartridgeMovement.request_id == request.id,
                    CartridgeMovement.movement_type == "issue",
                    Cartridge.status.in_(["issued", "installed"]),
                )
                .with_for_update()
            )
        )
        if issued_cartridges:
            raise HTTPException(status_code=409, detail="Issued cartridge must be removed and returned before fulfillment")
    previous = request.status
    request.status = target
    session.add(
        RequestEvent(
            request_id=request.id,
            actor_id=actor.id,
            event_type=target,
            from_status=previous,
            to_status=target,
            comment=payload.comment,
        )
    )
    session.commit()
    session.refresh(request)
    return request


@api.post("/requests/{request_id}/issue", response_model=CartridgeRead)
def issue_cartridge(
    request_id: str,
    payload: IssueCartridge,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> Cartridge:
    require_role(actor, "storekeeper", "admin")
    prior = session.scalar(select(CartridgeMovement).where(CartridgeMovement.idempotency_key == idempotency_key))
    if prior is not None:
        if prior.request_id != request_id or prior.to_user_id != payload.recipient_id or not cartridge_matches_code(prior.cartridge, payload.cartridge_code):
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different operation")
        response.status_code = status.HTTP_200_OK
        return prior.cartridge

    request = session.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.status != "approved":
        raise HTTPException(status_code=409, detail="Request must be approved before issue")
    if session.scalar(
        select(CartridgeMovement.id).where(
            CartridgeMovement.request_id == request.id,
            CartridgeMovement.movement_type == "issue",
        )
    ) is not None:
        raise HTTPException(status_code=409, detail="This request already has a cartridge issue")
    recipient = session.get(User, payload.recipient_id)
    if recipient is None or not recipient.active:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if request.department_id is not None and recipient.department_id != request.department_id:
        raise HTTPException(status_code=409, detail="Recipient is outside the request department")
    cartridge = find_cartridge(session, payload.cartridge_code, for_update=True)
    if cartridge is None:
        raise HTTPException(status_code=404, detail="Cartridge not found")
    if cartridge.status != "in_stock":
        raise HTTPException(status_code=409, detail="Cartridge is not available in stock")
    printer = session.get(Printer, request.printer_id)
    compatible_ids = {model.id for model in printer.printer_model.cartridge_models}
    if cartridge.cartridge_model_id not in compatible_ids:
        raise HTTPException(status_code=409, detail="Cartridge is not compatible with the requested printer")

    cartridge.status = "issued"
    previous_request_status = request.status
    request.status = "processing"
    session.add(
        CartridgeMovement(
            cartridge_id=cartridge.id,
            request_id=request.id,
            actor_id=actor.id,
            movement_type="issue",
            to_user_id=payload.recipient_id,
            from_status="in_stock",
            to_status="issued",
            idempotency_key=idempotency_key,
        )
    )
    session.add(
        RequestEvent(
            request_id=request.id,
            actor_id=actor.id,
            event_type="cartridge_issued",
            from_status=previous_request_status,
            to_status=request.status,
            comment=f"Issued cartridge {cartridge.asset_code}",
        )
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate or conflicting issue operation") from exc
    session.refresh(cartridge)
    return cartridge


@api.post("/requests/{request_id}/install", response_model=CartridgeRead)
def install_cartridge(
    request_id: str,
    payload: InstallCartridge,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> Cartridge:
    require_role(actor, "employee", "technician", "admin")
    prior = session.scalar(select(CartridgeMovement).where(CartridgeMovement.idempotency_key == idempotency_key))
    if prior is not None:
        if prior.movement_type != "install" or prior.request_id != request_id or not cartridge_matches_code(prior.cartridge, payload.cartridge_code):
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different operation")
        response.status_code = status.HTTP_200_OK
        return prior.cartridge

    request = session.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.status != "processing":
        raise HTTPException(status_code=409, detail="Request must be processing before installation")
    if request.created_by != actor.id and not actor.roles.intersection({"technician", "admin"}):
        raise HTTPException(status_code=403, detail="Only the recipient or an authorized technician may confirm installation")
    cartridge = find_cartridge(session, payload.cartridge_code, for_update=True)
    if cartridge is None:
        raise HTTPException(status_code=404, detail="Cartridge not found")
    if cartridge.status != "issued":
        raise HTTPException(status_code=409, detail="Cartridge must be issued before installation")
    if cartridge.cartridge_model_id not in {model.id for model in request.printer.printer_model.cartridge_models}:
        raise HTTPException(status_code=409, detail="Cartridge is not compatible with the requested printer")
    assignment = session.scalar(
        select(CartridgeMovement)
        .where(CartridgeMovement.cartridge_id == cartridge.id, CartridgeMovement.movement_type == "issue")
        .order_by(CartridgeMovement.created_at.desc(), CartridgeMovement.id.desc())
        .limit(1)
    )
    if assignment is None or assignment.request_id != request.id or assignment.to_user_id != request.created_by:
        raise HTTPException(status_code=409, detail="Cartridge was not issued to this request recipient")

    installation = CartridgeInstallation(
        cartridge_id=cartridge.id,
        printer_id=request.printer_id,
        request_id=request.id,
        installed_by=actor.id,
        install_counter=payload.counter_reading,
        condition_at_install=payload.condition,
    )
    cartridge.status = "installed"
    session.add(installation)
    session.add(
        CartridgeMovement(
            cartridge_id=cartridge.id,
            request_id=request.id,
            actor_id=actor.id,
            movement_type="install",
            from_user_id=request.created_by,
            to_status="installed",
            from_status="issued",
            counter_reading=payload.counter_reading,
            condition=payload.condition,
            idempotency_key=idempotency_key,
        )
    )
    session.add(
        RequestEvent(
            request_id=request.id,
            actor_id=actor.id,
            event_type="cartridge_installed",
            from_status=request.status,
            to_status=request.status,
            comment=f"Installed cartridge {cartridge.asset_code}",
        )
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Cartridge already has an active installation") from exc
    session.refresh(cartridge)
    return cartridge


@api.post("/requests/{request_id}/remove", response_model=CartridgeRead)
def remove_cartridge(
    request_id: str,
    payload: RemoveCartridge,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> Cartridge:
    require_role(actor, "technician", "storekeeper", "admin")
    prior = session.scalar(select(CartridgeMovement).where(CartridgeMovement.idempotency_key == idempotency_key))
    if prior is not None:
        if prior.movement_type != "remove" or prior.request_id != request_id or not cartridge_matches_code(prior.cartridge, payload.cartridge_code):
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different operation")
        response.status_code = status.HTTP_200_OK
        return prior.cartridge

    request = session.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.status != "processing":
        raise HTTPException(status_code=409, detail="Request must be processing before removal")
    cartridge = find_cartridge(session, payload.cartridge_code, for_update=True)
    if cartridge is None:
        raise HTTPException(status_code=404, detail="Cartridge not found")
    if cartridge.status != "installed":
        raise HTTPException(status_code=409, detail="Cartridge is not installed")
    installation = session.scalar(
        select(CartridgeInstallation)
        .where(CartridgeInstallation.cartridge_id == cartridge.id, CartridgeInstallation.removed_at.is_(None))
        .with_for_update()
    )
    if installation is None or installation.request_id != request.id or installation.printer_id != request.printer_id:
        raise HTTPException(status_code=409, detail="Active installation does not belong to this request")
    now = datetime.now(timezone.utc)
    installation.removed_at = now
    installation.removed_by = actor.id
    installation.remove_counter = payload.counter_reading
    installation.condition_at_removal = payload.condition
    cartridge.status = "issued"
    session.add(
        CartridgeMovement(
            cartridge_id=cartridge.id,
            request_id=request.id,
            actor_id=actor.id,
            movement_type="remove",
            from_user_id=request.created_by,
            from_status="installed",
            to_status="issued",
            counter_reading=payload.counter_reading,
            condition=payload.condition,
            note=payload.note,
            idempotency_key=idempotency_key,
        )
    )
    session.add(
        RequestEvent(
            request_id=request.id,
            actor_id=actor.id,
            event_type="cartridge_removed",
            from_status=request.status,
            to_status=request.status,
            comment=f"Removed cartridge {cartridge.asset_code}",
        )
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Conflicting cartridge removal") from exc
    session.refresh(cartridge)
    return cartridge


@api.post("/requests/{request_id}/return", response_model=CartridgeRead)
def return_cartridge(
    request_id: str,
    payload: ReturnCartridge,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> Cartridge:
    require_role(actor, "storekeeper", "admin")
    prior = session.scalar(select(CartridgeMovement).where(CartridgeMovement.idempotency_key == idempotency_key))
    if prior is not None:
        if (
            prior.movement_type != "return"
            or prior.request_id != request_id
            or prior.from_user_id != payload.recipient_id
            or not cartridge_matches_code(prior.cartridge, payload.cartridge_code)
        ):
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different operation")
        response.status_code = status.HTTP_200_OK
        return prior.cartridge

    request = session.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.status not in {"processing", "fulfilled"}:
        raise HTTPException(status_code=409, detail="Request is not in a state that accepts a cartridge return")
    cartridge = find_cartridge(session, payload.cartridge_code, for_update=True)
    if cartridge is None:
        raise HTTPException(status_code=404, detail="Cartridge not found")
    if cartridge.status != "issued":
        raise HTTPException(status_code=409, detail="Cartridge is not currently issued")
    last_movement = session.scalar(
        select(CartridgeMovement)
        .where(CartridgeMovement.cartridge_id == cartridge.id, CartridgeMovement.movement_type.in_(["issue", "return"]))
        .order_by(CartridgeMovement.created_at.desc(), CartridgeMovement.id.desc())
        .limit(1)
    )
    active_installation = session.scalar(
        select(CartridgeInstallation.id).where(
            CartridgeInstallation.cartridge_id == cartridge.id,
            CartridgeInstallation.removed_at.is_(None),
        )
    )
    if active_installation is not None:
        raise HTTPException(status_code=409, detail="Cartridge must be removed from the printer before return")
    if last_movement is None or last_movement.movement_type != "issue" or last_movement.request_id != request.id:
        raise HTTPException(status_code=409, detail="No active issue for this request and cartridge")
    if last_movement.to_user_id != payload.recipient_id:
        raise HTTPException(status_code=409, detail="Cartridge was issued to a different recipient")
    if payload.outcome == "writeoff":
        require_role(actor, "admin")
        if not payload.note:
            raise HTTPException(status_code=422, detail="A writeoff reason is required")

    status_by_outcome = {
        "stock": "in_stock",
        "refill": "sent_for_refill",
        "repair": "in_repair",
        "writeoff": "written_off",
    }
    previous_status = cartridge.status
    cartridge.status = status_by_outcome[payload.outcome]
    session.add(
        CartridgeMovement(
            cartridge_id=cartridge.id,
            request_id=request.id,
            actor_id=actor.id,
            movement_type="return",
            from_user_id=payload.recipient_id,
            from_status=previous_status,
            to_status=cartridge.status,
            counter_reading=payload.counter_reading,
            condition=payload.condition,
            note=payload.note,
            idempotency_key=idempotency_key,
        )
    )
    session.add(
        RequestEvent(
            request_id=request.id,
            actor_id=actor.id,
            event_type="cartridge_returned",
            from_status=request.status,
            to_status=request.status,
            comment=f"Returned {cartridge.asset_code}; next action: {payload.outcome}",
        )
    )
    if payload.outcome in {"refill", "repair"}:
        session.add(
            CartridgeService(
                cartridge_id=cartridge.id,
                request_id=request.id,
                service_type=payload.outcome,
                status="in_progress",
                condition_before=payload.condition,
            )
        )
    elif payload.outcome in {"stock", "writeoff"}:
        request.status = "fulfilled"
        session.add(
            RequestEvent(
                request_id=request.id,
                actor_id=actor.id,
                event_type="fulfilled",
                from_status="processing",
                to_status="fulfilled",
            )
        )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate or conflicting return operation") from exc
    session.refresh(cartridge)
    return cartridge


@api.post("/cartridges/{asset_code}/refill-completion", response_model=CartridgeRead)
def complete_refill(
    asset_code: str,
    payload: RefillCompletion,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> Cartridge:
    require_role(actor, "technician", "storekeeper", "admin")
    prior = session.scalar(select(CartridgeMovement).where(CartridgeMovement.idempotency_key == idempotency_key))
    if prior is not None:
        if prior.movement_type != "refill_return" or not cartridge_matches_code(prior.cartridge, asset_code):
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different operation")
        response.status_code = status.HTTP_200_OK
        return prior.cartridge
    cartridge = find_cartridge(session, asset_code, for_update=True)
    if cartridge is None:
        raise HTTPException(status_code=404, detail="Cartridge not found")
    if cartridge.status != "sent_for_refill":
        raise HTTPException(status_code=409, detail="Cartridge is not currently at a refill service")
    service = session.scalar(
        select(CartridgeService)
        .where(CartridgeService.cartridge_id == cartridge.id, CartridgeService.status == "in_progress")
        .with_for_update()
    )
    if service is None:
        raise HTTPException(status_code=409, detail="Active refill service record not found")
    if payload.cost is not None and payload.currency is None:
        raise HTTPException(status_code=422, detail="Currency is required when a service cost is supplied")
    previous_status = cartridge.status
    cartridge.status = "pending_inspection"
    cartridge.refill_count += 1
    service.status = "inspection"
    service.provider = payload.provider
    service.cost = payload.cost
    service.currency = payload.currency
    service.condition_after = payload.condition_after
    service.test_result = payload.test_result
    service.completion_key = idempotency_key
    service.finished_at = datetime.now(timezone.utc)
    session.add(
        CartridgeMovement(
            cartridge_id=cartridge.id,
            request_id=service.request_id,
            actor_id=actor.id,
            movement_type="refill_return",
            from_status=previous_status,
            to_status=cartridge.status,
            condition=payload.condition_after,
            note=payload.test_result,
            idempotency_key=idempotency_key,
        )
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate or conflicting refill completion") from exc
    session.refresh(cartridge)
    return cartridge


@api.post("/cartridges/{asset_code}/repair-completion", response_model=CartridgeRead)
def complete_repair(
    asset_code: str,
    payload: RepairCompletion,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> Cartridge:
    require_role(actor, "technician", "storekeeper", "admin")
    prior = session.scalar(select(CartridgeMovement).where(CartridgeMovement.idempotency_key == idempotency_key))
    if prior is not None:
        if prior.movement_type != "repair_return" or not cartridge_matches_code(prior.cartridge, asset_code):
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different operation")
        response.status_code = status.HTTP_200_OK
        return prior.cartridge
    cartridge = find_cartridge(session, asset_code, for_update=True)
    if cartridge is None:
        raise HTTPException(status_code=404, detail="Cartridge not found")
    if cartridge.status != "in_repair":
        raise HTTPException(status_code=409, detail="Cartridge is not currently at repair service")
    service = session.scalar(
        select(CartridgeService)
        .where(CartridgeService.cartridge_id == cartridge.id, CartridgeService.service_type == "repair", CartridgeService.status == "in_progress")
        .order_by(CartridgeService.started_at.desc(), CartridgeService.id.desc())
        .with_for_update()
    )
    if service is None:
        raise HTTPException(status_code=409, detail="Active repair record not found")
    if payload.cost is not None and payload.currency is None:
        raise HTTPException(status_code=422, detail="Currency is required when a service cost is supplied")
    previous_status = cartridge.status
    cartridge.status = "pending_inspection"
    service.status = "inspection"
    service.provider = payload.provider
    service.cost = payload.cost
    service.currency = payload.currency
    service.condition_after = payload.condition_after
    service.test_result = payload.test_result
    service.completion_key = idempotency_key
    service.finished_at = datetime.now(timezone.utc)
    session.add(
        CartridgeMovement(
            cartridge_id=cartridge.id,
            request_id=service.request_id,
            actor_id=actor.id,
            movement_type="repair_return",
            from_status=previous_status,
            to_status=cartridge.status,
            condition=payload.condition_after,
            note=payload.test_result,
            idempotency_key=idempotency_key,
        )
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate or conflicting repair completion") from exc
    session.refresh(cartridge)
    return cartridge


@api.post("/cartridges/{asset_code}/inspection", response_model=CartridgeRead)
def inspect_cartridge(
    asset_code: str,
    payload: CartridgeInspection,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
    session: Session = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> Cartridge:
    require_role(actor, "technician", "storekeeper", "admin")
    prior = session.scalar(select(CartridgeMovement).where(CartridgeMovement.idempotency_key == idempotency_key))
    if prior is not None:
        if prior.movement_type != "inspection" or not cartridge_matches_code(prior.cartridge, asset_code):
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different operation")
        return prior.cartridge
    cartridge = find_cartridge(session, asset_code, for_update=True)
    if cartridge is None:
        raise HTTPException(status_code=404, detail="Cartridge not found")
    if cartridge.status != "pending_inspection":
        raise HTTPException(status_code=409, detail="Cartridge is not awaiting inspection")
    if payload.result == "writeoff":
        require_role(actor, "admin")
        if not payload.note:
            raise HTTPException(status_code=422, detail="A writeoff reason is required")
    service = session.scalar(
        select(CartridgeService)
        .where(CartridgeService.cartridge_id == cartridge.id, CartridgeService.status == "inspection")
        .with_for_update()
    )
    if service is None:
        raise HTTPException(status_code=409, detail="Completed refill service record not found")
    status_by_result = {"stock": "in_stock", "repair": "in_repair", "writeoff": "written_off"}
    previous_status = cartridge.status
    cartridge.status = status_by_result[payload.result]
    service.status = "completed"
    service.inspection_result = payload.result
    if payload.condition:
        service.condition_after = payload.condition
    session.add(
        CartridgeMovement(
            cartridge_id=cartridge.id,
            request_id=service.request_id,
            actor_id=actor.id,
            movement_type="inspection",
            from_status=previous_status,
            to_status=cartridge.status,
            condition=payload.condition,
            note=payload.note,
            idempotency_key=idempotency_key,
        )
    )
    if payload.result == "repair":
        session.add(
            CartridgeService(
                cartridge_id=cartridge.id,
                request_id=service.request_id,
                service_type="repair",
                status="in_progress",
                condition_before=payload.condition or service.condition_after,
            )
        )
    if service.request_id is not None and payload.result in {"stock", "writeoff"}:
        request = session.scalar(select(ServiceRequest).where(ServiceRequest.id == service.request_id).with_for_update())
        if request is not None and request.status == "processing":
            request.status = "fulfilled"
            session.add(
                RequestEvent(
                    request_id=request.id,
                    actor_id=actor.id,
                    event_type="fulfilled",
                    from_status="processing",
                    to_status="fulfilled",
                    comment=f"Cartridge inspection outcome: {payload.result}",
                )
            )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate or conflicting inspection") from exc
    session.refresh(cartridge)
    return cartridge


app.include_router(api)
static_directory = Path(__file__).with_name("static")
if static_directory.is_dir():
    app.mount("/", StaticFiles(directory=static_directory, html=True), name="web")
