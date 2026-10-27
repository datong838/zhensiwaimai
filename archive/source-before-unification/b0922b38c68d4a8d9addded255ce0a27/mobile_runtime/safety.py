"""动作授权门；对外部副作用一律失败关闭。"""
from __future__ import annotations

from .contracts import ActionRequest, RiskLevel


class AuthorizationRequired(RuntimeError):
    pass


def authorize_action(request: ActionRequest) -> None:
    if request.risk_level is RiskLevel.EXTERNAL_EFFECT and not request.authorization_ref:
        raise AuthorizationRequired(
            f"动作 {request.action_id} 会产生外部副作用，缺少明确 authorization_ref"
        )
