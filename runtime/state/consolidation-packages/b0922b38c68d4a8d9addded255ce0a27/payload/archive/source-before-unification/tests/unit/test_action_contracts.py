import json

import pytest

from mobile_runtime.contracts import ActionRequest, RiskLevel
from mobile_runtime.safety import AuthorizationRequired, authorize_action


def test_read_only_action_needs_no_authorization():
    request = ActionRequest(action_id="probe-1", action_type="device_probe", risk_level=RiskLevel.READ_ONLY)
    authorize_action(request)


def test_external_effect_fails_closed_without_authorization():
    request = ActionRequest(action_id="send-1", action_type="send_message", risk_level=RiskLevel.EXTERNAL_EFFECT)
    with pytest.raises(AuthorizationRequired):
        authorize_action(request)


def test_external_effect_accepts_explicit_authorization_reference():
    request = ActionRequest(
        action_id="send-2",
        action_type="send_message",
        risk_level=RiskLevel.EXTERNAL_EFFECT,
        authorization_ref="user-approved-send-2",
    )
    authorize_action(request)
    assert json.loads(request.to_json())["riskLevel"] == "EXTERNAL_EFFECT"
