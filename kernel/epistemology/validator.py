"""输出验证器（质量门禁）。"""

from __future__ import annotations

import re

from kernel.epistemology.evidence import AnnotatedResponse, EvidenceLevel


class OutputValidator:
    def validate_response(
        self, response: AnnotatedResponse
    ) -> tuple[bool, list[str], AnnotatedResponse]:
        issues: list[str] = []
        for frag in response.fragments:
            text = frag.text or ""
            if re.search(r"```json\s*\{", text, re.IGNORECASE):
                issues.append("[ERROR] 检测到未处理的 JSON 块")
            if (
                frag.annotation
                and frag.annotation.level == EvidenceLevel.FACT
                and not frag.annotation.citations
            ):
                issues.append("[WARN] 事实性断言缺少引用来源")
            if frag.annotation and frag.annotation.level == EvidenceLevel.SPECULATION:
                if not re.search(r"可能|也许|推测|估计|不确定", text):
                    frag.text = f"{text}\n\n*注：以上为推测性分析，可能存在不确定性。*"
        ok = len([x for x in issues if x.startswith("[ERROR]")]) == 0
        return ok, issues, response

    def validate_raw_output(self, content: str) -> tuple[bool, str]:
        if content.strip().startswith("{") and '"chunks"' in content:
            return False, "抱歉，系统返回了未处理的数据格式。请稍后重试。"
        return True, content
