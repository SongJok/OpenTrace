#!/usr/bin/env python3
"""
Quick test: verifies DashScope API connectivity and chat.
Run from system terminal (iTerm/Terminal.app), NOT from Cursor:

  cd /Users/tuwan/work/code/agentos/opentrace
  python scripts/test_llm.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    # Unset proxy env vars that Cursor injects
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"]:
        os.environ.pop(key, None)

    from openai import AsyncOpenAI
    import httpx

    print("Testing DashScope API...")
    client = AsyncOpenAI(
        api_key="sk-03d982083aca40bb973ab70b8facc5e1",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=30,
        http_client=httpx.AsyncClient(trust_env=False),
    )
    try:
        resp = await client.chat.completions.create(
            model="qwen3-32b",
            messages=[{"role": "user", "content": "Say hello in one sentence."}],
            max_tokens=100,
            stream=False,
            extra_body={"enable_thinking": False},
        )
        content = resp.choices[0].message.content
        print(f"\n✓ DashScope API works!")
        print(f"  Response: {content}")
        return True
    except Exception as e:
        print(f"\n✗ DashScope API failed: {e}")
        return False


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
