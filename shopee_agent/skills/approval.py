"""Human-in-the-loop approval for high-risk skills. Supports multi-step approval workflows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.paths import APPROVALS_DIR

APPROVAL_DIR = APPROVALS_DIR
APPROVAL_DIR.mkdir(parents=True, exist_ok=True)

_APPROVED_IDS: set = set()
_REJECTED_IDS: set = set()


class ApprovalRequired(Exception):
    """Raised when a high-risk skill requires manual approval before execution."""

    def __init__(self, skill_name: str, request_id: str):
        self.skill_name = skill_name
        self.request_id = request_id
        super().__init__(f"Skill '{skill_name}' requires approval (request_id={request_id})")


class MultiStepApproval:
    """Multi-step approval workflow requiring multiple approvers.

    Each step requires a different person to approve before the skill can execute.
    """

    def __init__(self, skill_name: str, steps: list[str], reason: str = ""):
        self.skill_name = skill_name
        self.steps = steps  # list of approver names/roles
        self.reason = reason
        self._approvals: dict[str, bool] = {}
        self._rejections: dict[str, bool] = {}

    @property
    def is_fully_approved(self) -> bool:
        return len(self._approvals) >= len(self.steps)

    @property
    def is_rejected(self) -> bool:
        return len(self._rejections) > 0

    def approve(self, approver: str) -> bool:
        if approver in self.steps and approver not in self._approvals:
            self._approvals[approver] = True
            return True
        return False

    def reject(self, approver: str) -> bool:
        if approver in self.steps and approver not in self._rejections:
            self._rejections[approver] = True
            return True
        return False

    def get_status(self) -> dict[str, Any]:
        return {
            "skill": self.skill_name,
            "steps": self.steps,
            "approved_by": list(self._approvals.keys()),
            "rejected_by": list(self._rejections.keys()),
            "pending": [s for s in self.steps if s not in self._approvals and s not in self._rejections],
            "is_fully_approved": self.is_fully_approved,
            "is_rejected": self.is_rejected,
        }


def _next_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")


def request_approval(skill_name: str, reason: str = "", params: dict[str, Any] | None = None) -> str:
    """Create an approval request. Returns request_id.

    The skill should NOT execute until the request is approved via approve().
    """
    request_id = _next_id()
    entry = {
        "request_id": request_id,
        "skill": skill_name,
        "reason": reason,
        "params": params or {},
        "status": "pending",
        "created_at": datetime.now(UTC).isoformat(),
        "approved_at": None,
        "rejected_at": None,
    }
    _save_request(entry)
    return request_id


def approve(request_id: str) -> bool:
    """Approve a pending request. Returns True if found and approved."""
    entry = _load_request(request_id)
    if entry is None or entry.get("status") != "pending":
        return False
    entry["status"] = "approved"
    entry["approved_at"] = datetime.now(UTC).isoformat()
    _save_request(entry)
    _APPROVED_IDS.add(request_id)
    return True


def reject(request_id: str) -> bool:
    """Reject a pending request."""
    entry = _load_request(request_id)
    if entry is None or entry.get("status") != "pending":
        return False
    entry["status"] = "rejected"
    entry["rejected_at"] = datetime.now(UTC).isoformat()
    _save_request(entry)
    _REJECTED_IDS.add(request_id)
    return True


def is_approved(request_id: str) -> bool:
    return request_id in _APPROVED_IDS


def is_rejected(request_id: str) -> bool:
    return request_id in _REJECTED_IDS


def list_pending() -> list[dict[str, Any]]:
    """Return all pending approval requests."""
    return [e for e in _load_all() if e.get("status") == "pending"]


def list_all() -> list[dict[str, Any]]:
    return _load_all()


def _request_path(request_id: str) -> Path:
    return APPROVAL_DIR / f"{request_id}.json"


def _save_request(entry: dict[str, Any]) -> None:
    path = _request_path(entry["request_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_request(request_id: str) -> dict[str, Any] | None:
    path = _request_path(request_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_all() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not APPROVAL_DIR.exists():
        return entries
    for path in sorted(APPROVAL_DIR.iterdir()):
        if path.suffix == ".json":
            try:
                entries.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
    return entries


def approve_all_pending() -> int:
    """Approve all pending requests (use with caution)."""
    count = 0
    for entry in list_pending():
        if approve(entry["request_id"]):
            count += 1
    return count


def check_and_run(skill_name: str, run_fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Check if skill requires approval, request if so, run if approved.

    Returns dict with keys: ok, result/error, request_id (if approval needed).
    """
    from shopee_agent.skills.registry import default_registry
    cls = default_registry.get(skill_name)
    risk = getattr(cls, "risk_level", "LOW") if cls else "LOW"

    if risk != "HIGH":
        return {"ok": True, "result": run_fn(*args, **kwargs), "request_id": None}

    # HIGH risk — check approval
    request_id = request_approval(skill_name, reason="High-risk skill execution", params=kwargs)
    if is_approved(request_id):
        return {"ok": True, "result": run_fn(*args, **kwargs), "request_id": request_id}
    else:
        return {"ok": False, "error": f"requires approval (request_id={request_id})", "request_id": request_id}
