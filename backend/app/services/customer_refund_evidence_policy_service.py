from dataclasses import dataclass


@dataclass(frozen=True)
class CustomerRefundEvidencePolicy:
    required: tuple[str, ...]
    recommended: tuple[str, ...]


POLICIES: dict[str, CustomerRefundEvidencePolicy] = {
    "order_not_received": CustomerRefundEvidencePolicy(
        required=("receipt", "delivery_proof"),
        recommended=("gps_or_route_proof", "customer_contact_proof", "courier_statement"),
    ),
    "missing_item": CustomerRefundEvidencePolicy(
        required=("receipt", "preparation_proof"),
        recommended=("packaging_photo", "sealed_bag_photo", "order_details_screenshot"),
    ),
    "incorrect_item": CustomerRefundEvidencePolicy(
        required=("receipt", "preparation_proof"),
        recommended=("packaging_photo", "order_details_screenshot"),
    ),
    "damaged_order": CustomerRefundEvidencePolicy(
        required=("receipt", "packaging_photo"),
        recommended=("sealed_bag_photo",),
    ),
    "quality_issue": CustomerRefundEvidencePolicy(
        required=("receipt", "preparation_proof"),
        recommended=("packaging_photo",),
    ),
    "customer_refund": CustomerRefundEvidencePolicy(
        required=("receipt", "uber_screenshot"),
        recommended=("preparation_proof", "order_details_screenshot"),
    ),
    "order_error_adjustment": CustomerRefundEvidencePolicy(
        required=("receipt", "uber_screenshot"),
        recommended=("preparation_proof", "order_details_screenshot"),
    ),
    "chargeback": CustomerRefundEvidencePolicy(
        required=("receipt", "uber_screenshot"),
        recommended=("preparation_proof", "order_details_screenshot"),
    ),
    "unknown": CustomerRefundEvidencePolicy(
        required=("receipt", "uber_screenshot"),
        recommended=("preparation_proof", "order_details_screenshot"),
    ),
}


def evidence_policy_for_dispute(dispute_type: str) -> CustomerRefundEvidencePolicy:
    return POLICIES.get(dispute_type, POLICIES["unknown"])
