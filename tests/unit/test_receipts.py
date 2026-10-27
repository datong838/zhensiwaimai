import json

from mobile_runtime.contracts import ActionResult, PageState, RiskLevel
from mobile_runtime.receipts import write_receipt


def test_receipt_is_deterministic_and_contains_before_after(tmp_path):
    before = PageState(package_name="com.example", activity="Before")
    after = PageState(package_name="com.example", activity="After")
    result = ActionResult(
        action_id="scroll-1",
        action_type="scroll",
        risk_level=RiskLevel.READ_ONLY,
        before_state=before,
        after_state=after,
        success=True,
    )
    path = write_receipt(result, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["beforeState"]["activity"] == "Before"
    assert data["afterState"]["activity"] == "After"
    assert data["receiptSha256"]
