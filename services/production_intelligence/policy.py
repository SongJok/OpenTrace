"""连接器与生产能力的确定性最小权限策略。"""

from __future__ import annotations

from dataclasses import dataclass

from services.production_intelligence.domain import DataClassification, OperationRisk


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    approval_required: bool = False
    data_mode: str = "none"
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "approval_required": self.approval_required,
            "data_mode": self.data_mode,
            "reason": self.reason,
        }


_READ_MATRIX: dict[str, dict[str, str]] = {
    "customer_service": {
        "asset": "full",
        "knowledge": "full",
        "observability": "masked",
        "data": "user_scoped",
        "business": "user_scoped",
    },
    "operations": {
        "asset": "full",
        "knowledge": "full",
        "observability": "summary",
        "data": "business_scoped",
        "business": "business_scoped",
        "config": "full",
    },
    "product": {
        "asset": "full",
        "knowledge": "full",
        "observability": "summary",
        "data": "aggregate",
        "business": "aggregate",
        "config": "full",
        "code": "partial",
        "cicd": "summary",
    },
    "developer": {
        "asset": "full",
        "knowledge": "full",
        "observability": "full",
        "data": "restricted",
        "business": "restricted",
        "config": "full",
        "code": "full",
        "cicd": "full",
        "cmdb": "full",
        "kubernetes": "full",
    },
    "sre": {
        "asset": "full",
        "knowledge": "full",
        "observability": "full",
        "data": "restricted",
        "business": "restricted",
        "config": "full",
        "code": "full",
        "cicd": "full",
        "cmdb": "full",
        "kubernetes": "full",
    },
    "admin": {
        "asset": "full",
        "knowledge": "full",
        "observability": "full",
        "data": "full",
        "business": "full",
        "config": "full",
        "code": "full",
        "cicd": "full",
        "cmdb": "full",
        "kubernetes": "full",
    },
}

_WRITE_DOMAINS = {
    "operations": {"config"},
    "developer": {"config", "cicd"},
    "sre": {"config", "cicd", "kubernetes"},
    "admin": {
        "asset",
        "knowledge",
        "observability",
        "data",
        "business",
        "config",
        "code",
        "cicd",
        "cmdb",
        "kubernetes",
    },
}


class CapabilityPolicy:
    """默认拒绝的角色、领域、风险和数据分类策略。"""

    @staticmethod
    def normalize_role(role: str, *, is_superuser: bool = False) -> str:
        if is_superuser or role == "admin":
            return "admin"
        aliases = {
            "user": "customer_service",
            "employee": "customer_service",
            "customer-service": "customer_service",
            "ops": "operations",
            "operation": "operations",
            "dev": "developer",
        }
        return aliases.get((role or "").strip().lower(), (role or "").strip().lower())

    def authorize(
        self,
        *,
        role: str,
        domain: str,
        risk: str,
        classification: str = DataClassification.INTERNAL.value,
        environment: str = "shared",
        is_superuser: bool = False,
    ) -> PolicyDecision:
        normalized_role = self.normalize_role(role, is_superuser=is_superuser)
        normalized_domain = (domain or "").strip().lower()
        normalized_risk = (risk or "").strip().lower()
        read_mode = _READ_MATRIX.get(normalized_role, {}).get(normalized_domain)
        if not read_mode:
            return PolicyDecision(False, reason="role_domain_denied")

        if classification == DataClassification.RESTRICTED.value and normalized_role not in {
            "sre",
            "admin",
        }:
            return PolicyDecision(False, reason="restricted_classification_denied")

        if normalized_risk == OperationRisk.READ.value:
            return PolicyDecision(True, data_mode=read_mode, reason="read_allowed")

        if normalized_domain not in _WRITE_DOMAINS.get(normalized_role, set()):
            return PolicyDecision(False, reason="write_domain_denied")

        if normalized_risk not in {
            OperationRisk.WRITE_LOW.value,
            OperationRisk.WRITE_HIGH.value,
            OperationRisk.DESTRUCTIVE.value,
        }:
            return PolicyDecision(False, reason="unknown_operation_risk")

        # 所有生产写入都必须由 Responses 持久化审批点恢复后执行。
        if environment == "prod" or normalized_risk != OperationRisk.WRITE_LOW.value:
            return PolicyDecision(
                True,
                approval_required=True,
                data_mode=read_mode,
                reason="durable_approval_required",
            )
        return PolicyDecision(
            True,
            approval_required=True,
            data_mode=read_mode,
            reason="write_confirmation_required",
        )

    def role_projection(self, role: str, *, is_superuser: bool = False) -> dict[str, object]:
        normalized = self.normalize_role(role, is_superuser=is_superuser)
        return {
            "role": normalized,
            "read_domains": dict(_READ_MATRIX.get(normalized, {})),
            "write_domains": sorted(_WRITE_DOMAINS.get(normalized, set())),
            "default": "deny",
            "production_writes_require_approval": True,
            "destructive_writes_required_approvals": 2,
        }
