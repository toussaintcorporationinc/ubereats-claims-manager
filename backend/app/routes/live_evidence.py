from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_restaurant, get_accessible_restaurant_ids, get_current_user
from app.core.database import get_db
from app.models import ClaimOrder, EvidenceRequestTask, User
from app.routes.evidence_tasks import build_task_summary
from app.schemas.domain import EvidenceRequestPriority, EvidenceRequestTaskStatus, LiveEvidenceStationResponse

router = APIRouter(prefix="/v1/live-evidence", tags=["live-evidence"])

ACTIVE_STATUSES: tuple[EvidenceRequestTaskStatus, ...] = ("pending", "uploaded")
PRIORITY_RANK: dict[str, int] = {"urgent": 0, "high": 1, "normal": 2, "low": 3}

SAFE_CAPTURE_RULES = [
    "Imprimer uniquement le ticket TENNET lie a la commande.",
    "Photographier le ticket, la preuve demandee et les elements utiles dans la meme sequence terrain.",
    "Ne jamais inventer de montant, de commande ou de preuve.",
    "Ne jamais lire ni automatiser la tablette Uber Eats.",
    "Scanner le QR code du ticket pour envoyer la preuve dans le bon dossier.",
]


@router.get("/station", response_model=LiveEvidenceStationResponse)
def get_live_evidence_station(
    restaurant_id: int | None = Query(default=None),
    status_filter: EvidenceRequestTaskStatus | None = Query(default=None, alias="status"),
    priority: EvidenceRequestPriority | None = Query(default=None),
    assigned_to_me: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LiveEvidenceStationResponse:
    statement = select(EvidenceRequestTask).join(ClaimOrder)
    accessible_ids = get_accessible_restaurant_ids(db, current_user)

    if restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, restaurant_id)
        statement = statement.where(ClaimOrder.restaurant_id == restaurant_id)
    elif accessible_ids is not None:
        if not accessible_ids:
            return build_response([], limit=limit, offset=offset)
        statement = statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))

    if status_filter:
        statement = statement.where(EvidenceRequestTask.status == status_filter)
    else:
        statement = statement.where(EvidenceRequestTask.status.in_(ACTIVE_STATUSES))
    if priority:
        statement = statement.where(EvidenceRequestTask.priority == priority)
    if assigned_to_me:
        statement = statement.where(EvidenceRequestTask.assigned_to_user_id == current_user.id)

    tasks = db.scalars(statement).all()
    sorted_tasks = sorted(
        tasks,
        key=lambda task: (
            PRIORITY_RANK.get(task.priority, 9),
            task.due_at is None,
            task.due_at,
            -task.id,
        ),
    )
    page_tasks = sorted_tasks[offset : offset + limit]
    return build_response(page_tasks, total_tasks=sorted_tasks, limit=limit, offset=offset)


def build_response(
    tasks: list[EvidenceRequestTask],
    *,
    total_tasks: list[EvidenceRequestTask] | None = None,
    limit: int,
    offset: int,
) -> LiveEvidenceStationResponse:
    all_tasks = total_tasks if total_tasks is not None else tasks
    summaries = [build_task_summary(task) for task in tasks]
    return LiveEvidenceStationResponse(
        tasks=summaries,
        recommended_task_id=summaries[0].id if summaries else None,
        total_active_tasks=len(all_tasks),
        pending_count=sum(1 for task in all_tasks if task.status == "pending"),
        uploaded_count=sum(1 for task in all_tasks if task.status == "uploaded"),
        urgent_count=sum(1 for task in all_tasks if task.priority == "urgent"),
        high_priority_count=sum(1 for task in all_tasks if task.priority in {"urgent", "high"}),
        printer_mode="browser_print",
        bluetooth_supported=True,
        native_print_modes=["android_bluetooth_escpos"],
        native_print_contract_version="2026-06-12.android-escpos.v1",
        camera_capture_supported=True,
        native_printer_bridge_ready=True,
        native_printer_bridge_contract="POST /v1/evidence-tasks/{id}/print-ticket returns the ticket data consumed by TENNET Android for Bluetooth ESC/POS receipt printing.",
        safe_capture_rules=SAFE_CAPTURE_RULES,
        limit=limit,
        offset=offset,
    )
