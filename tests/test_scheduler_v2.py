from datetime import UTC, datetime

import pytest

from infra.responses.scheduler import (
    next_occurrence,
    next_occurrences,
    parse_schedule_expression,
    task_request_id,
)


def test_natural_schedule_requires_explicit_supported_expression() -> None:
    assert parse_schedule_expression("每天 09:30") == "FREQ=DAILY;BYHOUR=9;BYMINUTE=30;BYSECOND=0"
    assert (
        parse_schedule_expression("每周一 10:00")
        == "FREQ=WEEKLY;BYDAY=MO;BYHOUR=10;BYMINUTE=0;BYSECOND=0"
    )
    assert (
        parse_schedule_expression("工作日 18:15")
        == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=18;BYMINUTE=15;BYSECOND=0"
    )
    assert parse_schedule_expression("每隔 2 小时") == "FREQ=HOURLY;INTERVAL=2"
    assert (
        parse_schedule_expression("每周一、周三 10:00")
        == "FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=10;BYMINUTE=0;BYSECOND=0"
    )
    assert (
        parse_schedule_expression("每月 15 号 09:00")
        == "FREQ=MONTHLY;BYMONTHDAY=15;BYHOUR=9;BYMINUTE=0;BYSECOND=0"
    )
    with pytest.raises(ValueError):
        parse_schedule_expression("经常提醒我")


def test_next_occurrence_is_timezone_aware() -> None:
    result = next_occurrence(
        "FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
        "Asia/Shanghai",
        after=datetime(2026, 7, 15, 0, 0, tzinfo=UTC),
    )
    assert result is not None
    assert result.tzinfo is not None


def test_next_occurrences_respect_start_end_window() -> None:
    starts_at = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
    ends_at = datetime(2026, 7, 22, 2, 0, tzinfo=UTC)
    results = next_occurrences(
        "FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
        "Asia/Shanghai",
        after=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        starts_at=starts_at,
        ends_at=ends_at,
        limit=5,
    )

    assert results == [
        datetime(2026, 7, 20, 1, 0, tzinfo=UTC),
        datetime(2026, 7, 21, 1, 0, tzinfo=UTC),
        datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
    ]


def test_scheduled_request_id_is_stable_and_fits_database_limit() -> None:
    scheduled_for = datetime(2026, 7, 20, 5, 47, 28, 747968, tzinfo=UTC)
    first = task_request_id("fa219015-e3f2-4671-b061-5540facfee39", scheduled_for)
    second = task_request_id("fa219015-e3f2-4671-b061-5540facfee39", scheduled_for)

    assert first == second
    assert first.startswith("task:")
    assert len(first) <= 64
