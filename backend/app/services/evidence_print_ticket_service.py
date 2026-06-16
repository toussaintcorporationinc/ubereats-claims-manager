from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from html import escape
from io import BytesIO

import qrcode
from qrcode.image.svg import SvgPathImage
from sqlalchemy.orm import Session, object_session

from app.models import EvidenceRequestTask, EvidenceUploadLink, User
from app.schemas.domain import EvidenceUploadLinkRead
from app.services.audit import add_audit_log
from app.services.evidence_request_service import create_upload_link
from app.services.order_identity_resolution_service import resolve_identity_for_task

EVIDENCE_LABELS = {
    "receipt": "Ticket de caisse",
    "cancellation_proof": "Preuve d'annulation",
    "preparation_proof": "Preuve de preparation",
    "waste_photo": "Photo de gaspillage",
    "uber_screenshot": "Capture Uber",
    "delivery_proof": "Preuve de livraison",
    "packaging_photo": "Photo emballage",
    "sealed_bag_photo": "Photo sac ferme",
    "courier_statement": "Message livreur",
    "gps_or_route_proof": "Preuve GPS / trajet",
    "customer_contact_proof": "Preuve contact client",
    "order_details_screenshot": "Capture details commande",
    "other": "Autre preuve",
}


@dataclass(frozen=True)
class EvidencePrintTicket:
    task_id: int
    order_id: int
    restaurant_id: int
    restaurant_name: str
    uber_order_number: str
    customer_name: str | None
    required_evidence_type: str
    required_evidence_label: str
    title: str
    description: str | None
    order_amount: Decimal | None
    currency: str
    due_at: datetime | None
    ticket_reference: str
    upload_link: EvidenceUploadLink
    upload_url: str
    qr_svg: str
    print_html: str

    def as_response_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "order_id": self.order_id,
            "restaurant_id": self.restaurant_id,
            "restaurant_name": self.restaurant_name,
            "uber_order_number": self.uber_order_number,
            "customer_name": self.customer_name,
            "required_evidence_type": self.required_evidence_type,
            "required_evidence_label": self.required_evidence_label,
            "title": self.title,
            "description": self.description,
            "order_amount": self.order_amount,
            "currency": self.currency,
            "due_at": self.due_at,
            "ticket_reference": self.ticket_reference,
            "upload_link": EvidenceUploadLinkRead.model_validate(self.upload_link),
            "upload_url": self.upload_url,
            "qr_svg": self.qr_svg,
            "print_html": self.print_html,
        }


def create_print_ticket(
    db: Session,
    task: EvidenceRequestTask,
    current_user: User,
    *,
    expires_in_hours: int | None = None,
    max_uses: int | None = 1,
) -> EvidencePrintTicket:
    upload_link, _token, upload_url = create_upload_link(
        db,
        task,
        current_user,
        expires_in_hours=expires_in_hours,
        max_uses=max_uses or 1,
    )
    ticket_reference = f"PREUVE-{task.id}-{upload_link.id}"
    evidence_label = EVIDENCE_LABELS.get(task.required_evidence_type, task.required_evidence_type)
    qr_svg = build_qr_svg(upload_url)
    print_html = build_ticket_html(
        task=task,
        upload_link=upload_link,
        upload_url=upload_url,
        qr_svg=qr_svg,
        ticket_reference=ticket_reference,
        evidence_label=evidence_label,
    )
    add_audit_log(
        db,
        entity_type="evidence_request_task",
        entity_id=task.id,
        action="evidence_print_ticket.created",
        user_id=current_user.id,
        new_value={
            "upload_link_id": upload_link.id,
            "order_id": task.order_id,
            "restaurant_id": task.restaurant_id,
            "required_evidence_type": task.required_evidence_type,
            "ticket_reference": ticket_reference,
            "max_uses": upload_link.max_uses,
            "expires_at": upload_link.expires_at,
        },
    )
    order = task.order
    identity = resolve_identity_for_task(db, task)
    order_label = (identity.best_order_label if identity else None) or order.uber_order_number
    customer_name = identity.customer_name or order.customer_name
    order_amount = identity.order_amount if identity.order_amount is not None else order.order_amount
    currency = identity.currency or order.currency
    return EvidencePrintTicket(
        task_id=task.id,
        order_id=order.id,
        restaurant_id=order.restaurant_id,
        restaurant_name=order.restaurant.name,
        uber_order_number=order_label,
        customer_name=customer_name,
        required_evidence_type=task.required_evidence_type,
        required_evidence_label=evidence_label,
        title=task.title,
        description=task.description,
        order_amount=order_amount,
        currency=currency,
        due_at=task.due_at,
        ticket_reference=ticket_reference,
        upload_link=upload_link,
        upload_url=upload_url,
        qr_svg=qr_svg,
        print_html=print_html,
    )


def build_qr_svg(value: str) -> str:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage, attrib={"class": "proof-ticket-qr"})
    stream = BytesIO()
    image.save(stream)
    svg = stream.getvalue().decode("utf-8")
    svg_start = svg.find("<svg")
    return svg[svg_start:] if svg_start >= 0 else svg


def build_ticket_html(
    *,
    task: EvidenceRequestTask,
    upload_link: EvidenceUploadLink,
    upload_url: str,
    qr_svg: str,
    ticket_reference: str,
    evidence_label: str,
) -> str:
    order = task.order
    db = object_session(task)
    identity = resolve_identity_for_task(db, task) if db is not None else None
    order_label = (identity.best_order_label if identity else None) or order.uber_order_number
    amount = format_amount(
        identity.order_amount if identity and identity.order_amount is not None else order.order_amount,
        (identity.currency or order.currency) if identity else order.currency,
    )
    customer_name = (identity.customer_name if identity else None) or order.customer_name or "-"
    order_date_value = (identity.order_date if identity else None) or order.order_date
    order_time_value = (identity.order_time if identity else None) or order.order_time
    order_date = order_date_value.strftime("%Y-%m-%d") if order_date_value else "-"
    order_time = order_time_value.strftime("%H:%M") if order_time_value else "-"
    due_at = format_datetime(task.due_at)
    expires_at = format_datetime(upload_link.expires_at)
    description = escape(task.description or "Prenez la photo demandee et envoyez-la avec ce QR code.")
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(order.restaurant.name)} - preuve commande {escape(order_label)}</title>
  <style>
    body {{ margin: 0; background: #fff; color: #111; font-family: Arial, sans-serif; }}
    .ticket {{ width: 72mm; padding: 5mm; }}
    .center {{ text-align: center; }}
    .brand {{ font-size: 18px; font-weight: 900; letter-spacing: 0.4px; overflow-wrap: anywhere; }}
    .muted {{ color: #555; font-size: 11px; }}
    .line {{ border-top: 1px dashed #333; margin: 10px 0; }}
    .row {{ display: flex; justify-content: space-between; gap: 8px; font-size: 12px; margin: 5px 0; }}
    .row strong {{ text-align: right; overflow-wrap: anywhere; }}
    .qr svg {{ width: 44mm; height: 44mm; }}
    .instructions {{ font-size: 12px; line-height: 1.35; }}
    .reference {{ font-size: 12px; font-weight: 800; overflow-wrap: anywhere; }}
    @page {{ size: 80mm auto; margin: 0; }}
  </style>
</head>
<body>
  <main class="ticket">
    <div class="center">
      <div class="brand">{escape(order.restaurant.name)}</div>
      <div class="muted">COMMANDE UBER - FICHE TERRAIN</div>
    </div>
    <div class="line"></div>
    <div class="row"><span>Commande Uber</span><strong>{escape(order_label)}</strong></div>
    <div class="row"><span>Client</span><strong>{escape(customer_name)}</strong></div>
    <div class="row"><span>Date commande</span><strong>{escape(order_date)}</strong></div>
    <div class="row"><span>Heure commande</span><strong>{escape(order_time)}</strong></div>
    <div class="row"><span>Montant</span><strong>{escape(amount)}</strong></div>
    <div class="row"><span>Preuve attendue</span><strong>{escape(evidence_label)}</strong></div>
    <div class="row"><span>Echeance</span><strong>{escape(due_at)}</strong></div>
    <div class="row"><span>Reference preuve</span><strong>{escape(ticket_reference)}</strong></div>
    <div class="line"></div>
    <div class="center qr">{qr_svg}</div>
    <p class="instructions">
      1. Retrouvez cette commande dans Uber avec le client, la date et le numero.<br />
      2. Imprimez le vrai ticket Uber et agrafez-le sur la commande.<br />
      3. Photographiez l'ensemble puis scannez le QR code pour envoyer la photo au bon dossier.
    </p>
    <p class="instructions">{description}</p>
    <div class="line"></div>
    <div class="muted">Lien valable jusqu'au {escape(expires_at)}. Usage limite: {upload_link.max_uses}.</div>
    <div class="reference">{escape(ticket_reference)}</div>
  </main>
</body>
</html>"""


def format_amount(amount: Decimal | None, currency: str) -> str:
    if amount is None:
        return "-"
    return f"{amount:.2f} {currency}"


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M")
