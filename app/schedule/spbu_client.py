from __future__ import annotations

import asyncio
from datetime import date

import httpx

from app.config import Settings, get_settings
from app.schedule.source_models import EducatorScheduleResponse, GroupScheduleResponse


class SpbuTimetableError(RuntimeError):
    pass


class SpbuTimetableClient:
    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._external_client = client

    async def fetch_group_schedule(
        self,
        group_id: int,
        date_from: date,
        date_to: date,
        *,
        timetable: int = 1,
    ) -> GroupScheduleResponse:
        if date_to < date_from:
            raise ValueError("date_to must not be earlier than date_from")

        path = (
            f"/api/v1/groups/{group_id}/events/"
            f"{date_from.isoformat()}/{date_to.isoformat()}"
        )
        url = str(self.settings.spbu_base_url).rstrip("/") + path
        headers = {
            "Accept": "application/json",
            "Accept-Language": "ru",
            "User-Agent": "spbu-assistant/0.1 (+self-hosted student timetable client)",
        }

        owns_client = self._external_client is None
        client = self._external_client or httpx.AsyncClient(
            timeout=self.settings.spbu_request_timeout_seconds,
            headers=headers,
        )

        try:
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    response = await client.get(
                        url,
                        params={"timetable": timetable},
                        headers=headers,
                    )
                    response.raise_for_status()
                    return GroupScheduleResponse.model_validate(response.json())
                except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
                    last_error = exc
                    if (
                        isinstance(exc, httpx.HTTPStatusError)
                        and exc.response.status_code < 500
                    ):
                        break
                    if attempt < 2:
                        await asyncio.sleep(0.25 * (2**attempt))
            raise SpbuTimetableError(
                f"Unable to fetch SPbU timetable for group {group_id}"
            ) from last_error
        finally:
            if owns_client:
                await client.aclose()

    async def fetch_educator_schedule(
        self,
        educator_id: int,
        date_from: date,
        date_to: date,
    ) -> EducatorScheduleResponse:
        if date_to < date_from:
            raise ValueError("date_to must not be earlier than date_from")
        url = (
            str(self.settings.spbu_base_url).rstrip("/")
            + f"/api/v1/educators/{educator_id}/events/"
            + f"{date_from.isoformat()}/{date_to.isoformat()}"
        )
        headers = {
            "Accept": "application/json",
            "Accept-Language": "ru",
            "User-Agent": "spbu-assistant/0.1 (+self-hosted student timetable client)",
        }
        owns_client = self._external_client is None
        client = self._external_client or httpx.AsyncClient(
            timeout=self.settings.spbu_request_timeout_seconds,
            headers=headers,
        )
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return EducatorScheduleResponse.model_validate(response.json())
        except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
            raise SpbuTimetableError(
                f"Unable to fetch SPbU timetable for educator {educator_id}"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
