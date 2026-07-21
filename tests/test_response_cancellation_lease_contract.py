from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cancellation_keeps_live_worker_lease_until_worker_exits() -> None:
    responses_source = (ROOT / "gateway/api_gateway/routers/responses.py").read_text(
        encoding="utf-8"
    )
    cancel_source = responses_source.split("async def cancel_response(", 1)[1]

    assert "claimed_by_worker = bool(record.lease_owner)" in cancel_source
    assert "if not claimed_by_worker:" in cancel_source

    repository_source = (ROOT / "infra/responses/repository.py").read_text(encoding="utf-8")
    assert 'ResponseRecord.status.in_(("in_progress", "cancelled"))' in repository_source
