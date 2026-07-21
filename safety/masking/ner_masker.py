from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)

_ENTITY_PATTERNS: dict[str, str] = {
    "EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    "PHONE_CN": r"(?<!\d)1[3-9]\d{9}(?!\d)",
    "PHONE_INTL": r"\+?\d{1,3}[\s-]?\(?\d{1,4}\)?[\s.-]?\d{1,4}[\s.-]?\d{1,4}[\s.-]?\d{1,4}",
    "CREDIT_CARD": r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)",
    "ID_CN": r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)",
    "IP_ADDRESS": r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?!\d)",
    "PERSON_CN": r"(?:[一-鿿]{1,4}(?:先生|女士|老师|经理|总监|主任|总|董|博士|教授|同学|老师|工|师傅|阿姨|叔叔|爷爷|奶奶|小朋友|小[明红丽强华伟芳静敏洁玲萍]))",
    "LOCATION_CN": r"(?:[一-鿿]{2,6}(?:省|市|区|县|镇|乡|村|路|街|巷|号|楼|栋|单元|小区|花园|大厦|广场|中心|酒店|宾馆))",
    "ORG_CN": r"(?:[一-鿿]{2,20}(?:公司|集团|银行|医院|学校|大学|学院|研究所|研究院|中心|局|厅|部|委|会|所|社|厂|行|店|馆|站))",
}

_ENTITY_ORDER: list[str] = [
    "EMAIL",
    "PHONE_CN",
    "PHONE_INTL",
    "CREDIT_CARD",
    "ID_CN",
    "IP_ADDRESS",
    "PERSON_CN",
    "LOCATION_CN",
    "ORG_CN",
]

_PLACEHOLDER_RE = re.compile(r"\{MASK_(\w+?)_(\d+)\}")


@dataclass
class MaskResult:
    """Result of masking a text string."""

    masked: str = ""
    mapping: dict[str, str] = field(default_factory=dict)
    pii_detected: bool = False


class NERMasker:
    """Replace detected PII entities with reversible typed placeholders.

    Usage::

        masker = NERMasker()
        result = masker.mask_input("请帮我查一下张三的账户，手机号13800138000")
        # result.masked: "请帮我查一下{MASK_PERSON_CN_0}的账户，手机号{MASK_PHONE_CN_0}"
        # result.mapping: {"{MASK_PERSON_CN_0}": "张三", ...}
        restored = masker.unmask_output(result.masked, result.mapping)
    """

    def __init__(
        self,
        entity_types: list[str] | None = None,
        enabled: bool | None = None,
    ) -> None:
        config_value: str = getattr(settings, "kernel_pii_entity_types", "")
        allowed = self._parse_entity_types(config_value) if config_value else None
        ent_name = entity_types or allowed or _ENTITY_ORDER.copy()
        self._patterns: dict[str, str] = {
            name: _ENTITY_PATTERNS[name]
            for name in ent_name
            if name in _ENTITY_PATTERNS
        }
        self._enabled: bool
        if enabled is not None:
            self._enabled = enabled
        else:
            self._enabled = bool(getattr(settings, "kernel_pii_masking_enabled", False))

    @staticmethod
    def _parse_entity_types(config_value: str) -> list[str]:
        raw = config_value.strip()
        if not raw:
            return []
        return [t.strip() for t in raw.split(",") if t.strip()]

    @property
    def enabled(self) -> bool:
        return self._enabled

    def mask_input(self, text: str) -> MaskResult:
        """Replace PII entities in *text* with typed placeholders."""
        sanitized = text
        mapping: dict[str, str] = {}
        counters: dict[str, int] = {}
        pii_detected = False

        for ent_name in _ENTITY_ORDER:
            pattern = self._patterns.get(ent_name)
            if pattern is None:
                continue
            compiled = re.compile(pattern)
            original = sanitized
            idx = counters.get(ent_name, 0)
            while True:
                m = compiled.search(sanitized)
                if not m:
                    break
                placeholder = "{MASK_%s_%d}" % (ent_name, idx)
                mapping[placeholder] = m.group(0)
                sanitized = sanitized[: m.start()] + placeholder + sanitized[m.end():]  # noqa: E203
                idx += 1
                pii_detected = True
            counters[ent_name] = idx
            if sanitized != original:
                pass  # continue scanning with updated counters

        logger.info(
            "PII masked in input",
            entity_count=len(mapping),
            entity_types=list(counters.keys()),
        )
        return MaskResult(masked=sanitized, mapping=mapping, pii_detected=pii_detected)

    def unmask_output(self, text: str, mapping: dict[str, str]) -> str:
        """Reverse placeholder substitution to restore original values."""
        result = text
        placeholder: str
        original: str
        for placeholder, original in mapping.items():
            result = result.replace(placeholder, original)
        return result

    def scan_pii(self, text: str) -> dict[str, list[str]]:
        """Return detected PII entities by type (for audit logging)."""
        findings: dict[str, list[str]] = {}
        ent_name: str
        pattern: str
        for ent_name, pattern in self._patterns.items():
            matches = re.findall(pattern, text)
            if matches:
                findings[ent_name] = matches
        return findings


_masker: NERMasker | None = None


def get_ner_masker() -> NERMasker:
    global _masker
    if _masker is None:
        _masker = NERMasker()
    return _masker
