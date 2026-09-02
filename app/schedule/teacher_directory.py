from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser

import httpx

from app.config import Settings, get_settings
from app.schedule.normalizer import normalize_event, normalize_text
from app.schedule.spbu_client import SpbuTimetableClient, SpbuTimetableError

_EDUCATOR_PATH = re.compile(r"^/EducatorEvents/(\d+)$")


@dataclass(frozen=True, slots=True)
class TeacherLink:
    source_id: int
    display_name: str


class _TeacherLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[TeacherLink, ...]] = []
        self._event_depth = 0
        self._teachers: list[TeacherLink] = []
        self._anchor_id: int | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "li":
            classes = set((attributes.get("class") or "").split())
            if self._event_depth or "common-list-item" in classes:
                self._event_depth += 1
        if tag == "a" and self._event_depth:
            match = _EDUCATOR_PATH.match(attributes.get("href") or "")
            if match:
                self._anchor_id = int(match.group(1))
                self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._anchor_id is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor_id is not None:
            self._teachers.append(
                TeacherLink(self._anchor_id, " ".join(self._anchor_text).strip())
            )
            self._anchor_id = None
            self._anchor_text = []
        if tag == "li" and self._event_depth:
            self._event_depth -= 1
            if self._event_depth == 0:
                self.events.append(tuple(self._teachers))
                self._teachers = []


def parse_teacher_links(html: str) -> tuple[tuple[TeacherLink, ...], ...]:
    parser = _TeacherLinkParser()
    parser.feed(html)
    return tuple(parser.events)


def _week_bounds(target: date) -> tuple[date, date]:
    monday = target - timedelta(days=target.weekday())
    return monday, monday + timedelta(days=6)


class TeacherDirectoryClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def teachers_for_lesson(
        self,
        group_source_id: int,
        starts_at: datetime,
        subject: str,
        location_text: str | None,
    ) -> tuple[TeacherLink, ...]:
        range_start, range_end = _week_bounds(starts_at.date())
        timeout = self.settings.spbu_request_timeout_seconds
        base = str(self.settings.spbu_base_url).rstrip("/")
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as http:
            try:
                await http.post(
                    base + "/Base/SetClientCultureCookie",
                    data={"clientCultureName": "ru"},
                )
                html_response = await http.get(
                    base
                    + f"/AMCP/StudentGroupEvents/Primary/{group_source_id}/"
                    + range_start.isoformat()
                )
                html_response.raise_for_status()
                schedule = await SpbuTimetableClient(
                    self.settings,
                    http,
                ).fetch_group_schedule(group_source_id, range_start, range_end)
            except (httpx.HTTPError, SpbuTimetableError) as exc:
                raise SpbuTimetableError(
                    "Unable to resolve SPbU educator links"
                ) from exc

        links_by_event = parse_teacher_links(html_response.text)
        events = [event for day in schedule.days for event in day.events]
        wanted_subject = normalize_text(subject)
        wanted_location = normalize_text(location_text or "")
        for index, event in enumerate(events):
            normalized = normalize_event(group_source_id, event)
            if normalized.starts_at != starts_at:
                continue
            if normalized.subject_normalized != wanted_subject:
                continue
            if normalize_text(normalized.location_text or "") != wanted_location:
                continue
            if index < len(links_by_event):
                return links_by_event[index]
        return ()
