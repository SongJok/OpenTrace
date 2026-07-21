from kernel.agent_loop.prompt import PLATFORM_PROMPT


def test_platform_prompt_requires_mature_safe_text_output() -> None:
    assert "先给结论" in PLATFORM_PROMPT
    assert "GitHub Flavored Markdown" in PLATFORM_PROMPT
    assert "带语言标识的围栏代码块" in PLATFORM_PROMPT
    assert "数学公式使用 LaTeX" in PLATFORM_PROMPT
    assert "不要输出原始 HTML" in PLATFORM_PROMPT
