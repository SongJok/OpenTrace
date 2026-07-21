from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_goal_mutations_refresh_server_generated_fields_before_serializing() -> None:
    source = (ROOT / "gateway/api_gateway/routers/agent_resources.py").read_text(encoding="utf-8")

    for function_name, next_function in (
        ("create_goal", "get_goal"),
        ("update_goal", "goal_action"),
        ("goal_action", "_goal"),
    ):
        function_source = source.split(f"async def {function_name}(", 1)[1].split(
            (
                f"\ndef {next_function}("
                if next_function == "_goal"
                else f"\nasync def {next_function}("
            ),
            1,
        )[0]
        assert (
            "await db.commit()\n    await db.refresh(row)\n    return _goal(row)" in function_source
        )
