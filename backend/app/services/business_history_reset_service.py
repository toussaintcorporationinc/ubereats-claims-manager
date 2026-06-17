from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    AppealAttempt,
    AppealWorkflow,
    AutopilotAction,
    AutopilotRun,
    ClaimOrder,
    ClaimResponseReview,
    CustomerRefundDisputeReview,
    CustomerRefundEvidenceRequirement,
    EmailDraft,
    EmailProviderDraft,
    EmailThread,
    EvidenceAnalysisResult,
    EvidenceAttachmentDecision,
    EvidenceFile,
    EvidenceImportBatch,
    EvidenceImportedFile,
    EvidenceMatchCandidate,
    EvidenceRequestTask,
    EvidenceUploadLink,
    FollowUpTask,
    GmailResponseAnalysis,
    GmailSyncState,
    ImportBatch,
    ImportRow,
    InboundEmailMessage,
    RefusalAnalysis,
    SmartImportPreviewBatch,
    SmartImportPreviewFile,
    UberCustomerRefundDispute,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberReportingImportBatch,
    UberReportingImportRow,
    UberReconciliationResult,
    UberReconciliationRun,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log

RESET_CONFIRMATION = "RESET_TENNET_BUSINESS_HISTORY"


class BusinessHistoryResetError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def reset_business_history(db: Session, *, user_id: int, confirmation: str) -> dict[str, int]:
    if confirmation != RESET_CONFIRMATION:
        raise BusinessHistoryResetError("Confirmation phrase is invalid", 400)
    counts: dict[str, int] = {}
    for model in reset_order():
        counts[model.__tablename__] = db.query(model).delete(synchronize_session=False)
    add_audit_log(
        db,
        entity_type="business_history_reset",
        entity_id=user_id,
        action="business_history.reset",
        user_id=user_id,
        new_value={
            "preserved": [
                "users",
                "restaurants",
                "user_restaurant_access",
                "email_accounts",
                "email_account_restaurant_mappings",
                "uber_store_mappings",
                "uber_integration_accounts",
            ],
            "deleted_counts": counts,
            "reset_at": utc_now().isoformat(),
        },
    )
    db.commit()
    return counts


def reset_order() -> list[type]:
    return [
        EvidenceAttachmentDecision,
        EvidenceMatchCandidate,
        EvidenceAnalysisResult,
        EvidenceImportedFile,
        EvidenceImportBatch,
        EvidenceUploadLink,
        EvidenceRequestTask,
        CustomerRefundDisputeReview,
        CustomerRefundEvidenceRequirement,
        RefusalAnalysis,
        AppealAttempt,
        AppealWorkflow,
        AutopilotAction,
        AutopilotRun,
        FollowUpTask,
        GmailResponseAnalysis,
        ClaimResponseReview,
        InboundEmailMessage,
        EmailProviderDraft,
        EmailDraft,
        EmailThread,
        EvidenceFile,
        UberCustomerRefundDispute,
        UberReconciliationResult,
        UberReconciliationRun,
        UberReportingImportRow,
        UberReportingImportBatch,
        UberFinancialTransaction,
        UberOrderSnapshot,
        ImportRow,
        ImportBatch,
        SmartImportPreviewFile,
        SmartImportPreviewBatch,
        ClaimOrder,
        GmailSyncState,
    ]
