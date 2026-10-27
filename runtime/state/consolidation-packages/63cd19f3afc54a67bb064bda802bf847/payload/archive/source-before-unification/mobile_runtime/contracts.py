"""跨平台动作、页面状态与执行结果合同。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class RiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    LOCAL_EDIT = "LOCAL_EDIT"
    EXTERNAL_EFFECT = "EXTERNAL_EFFECT"


@dataclass(frozen=True)
class PageState:
    package_name: Optional[str] = None
    activity: Optional[str] = None
    screenshot_path: Optional[str] = None
    screenshot_sha256: Optional[str] = None
    hierarchy_path: Optional[str] = None
    hierarchy_sha256: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "packageName": self.package_name,
            "activity": self.activity,
            "screenshotPath": self.screenshot_path,
            "screenshotSha256": self.screenshot_sha256,
            "hierarchyPath": self.hierarchy_path,
            "hierarchySha256": self.hierarchy_sha256,
        }


@dataclass(frozen=True)
class ActionRequest:
    action_id: str
    action_type: str
    risk_level: RiskLevel
    target_package: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    expected_page: Optional[Dict[str, str]] = None
    authorization_ref: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actionId": self.action_id,
            "actionType": self.action_type,
            "riskLevel": self.risk_level.value,
            "targetPackage": self.target_package,
            "parameters": self.parameters or {},
            "expectedPage": self.expected_page or {},
            "authorizationRef": self.authorization_ref,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    action_type: str
    risk_level: RiskLevel
    before_state: PageState
    after_state: PageState
    success: bool
    device_id: Optional[str] = None
    app_package: Optional[str] = None
    selector_used: Optional[Dict[str, str]] = None
    failure_reason: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actionId": self.action_id,
            "actionType": self.action_type,
            "riskLevel": self.risk_level.value,
            "deviceId": self.device_id,
            "appPackage": self.app_package,
            "beforeState": self.before_state.to_dict(),
            "afterState": self.after_state.to_dict(),
            "selectorUsed": self.selector_used or {},
            "success": self.success,
            "failureReason": self.failure_reason,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }
