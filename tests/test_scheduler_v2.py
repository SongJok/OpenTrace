from datetime import UTC, datetime

import pytest

from infra.responses.scheduler import next_occurrence, parse_schedule_expression


def test_natural_schedule_requires_explicit_supported_expression() -> None:
    assert parse_schedule_expression("每天 09:30") == "FREQ=DAILY;BYHOUR=9;BYMINUTE=30;BYSECOND=0"
    assert parse_schedule_expression("每周一 10:00") == "FREQ=WEEKLY;BYDAY=MO;BYHOUR=10;BYMINUTE=0;BYSECOND=0"
    assert parse_schedule_expression("工作日 18:15") == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=18;BYMINUTE=15;BYSECOND=0"
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
