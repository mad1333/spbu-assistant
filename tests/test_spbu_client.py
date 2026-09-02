from datetime import date

import httpx
import pytest
import respx

from app.config import Settings
from app.schedule.spbu_client import SpbuTimetableClient, SpbuTimetableError


@pytest.mark.asyncio
@respx.mock
async def test_fetches_official_group_endpoint() -> None:
    route = respx.get(
        "https://timetable.spbu.ru/api/v1/groups/474999/events/2026-08-31/2026-09-06"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "StudentGroupId": 474999,
                "StudentGroupDisplayName": "26.Б05-бд",
                "Days": [],
            },
        )
    )
    settings = Settings(spbu_base_url="https://timetable.spbu.ru")

    response = await SpbuTimetableClient(settings).fetch_group_schedule(
        474999,
        date(2026, 8, 31),
        date(2026, 9, 6),
    )

    assert route.called
    assert route.calls[0].request.url.params["timetable"] == "1"
    assert response.group_id == 474999


@pytest.mark.asyncio
@respx.mock
async def test_non_retryable_error_is_wrapped() -> None:
    respx.get(
        "https://timetable.spbu.ru/api/v1/groups/474999/events/2026-08-31/2026-09-06"
    ).mock(return_value=httpx.Response(404))
    settings = Settings(spbu_base_url="https://timetable.spbu.ru")

    with pytest.raises(SpbuTimetableError):
        await SpbuTimetableClient(settings).fetch_group_schedule(
            474999,
            date(2026, 8, 31),
            date(2026, 9, 6),
        )
