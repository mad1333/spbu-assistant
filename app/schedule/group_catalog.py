from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database.models import StudentGroup

logger = logging.getLogger(__name__)

LEVEL_ORDER = ("Бакалавриат", "Магистратура", "Аспирантура")
LEVEL_TOKENS = {
    "bachelor": "Бакалавриат",
    "master": "Магистратура",
    "postgraduate": "Аспирантура",
}
TOKEN_BY_LEVEL = {label: token for token, label in LEVEL_TOKENS.items()}
_PROGRAM_PATH = re.compile(r"^/AMCP/StudyProgram/(\d+)$")
_GROUP_PATH = re.compile(r"/AMCP/StudentGroupEvents/Primary/(\d+)")


def _supported_level(value: str) -> str | None:
    folded = " ".join(value.casefold().split())
    if folded.startswith(("доп", "additional")):
        return None
    if "бакалавр" in folded or "bachelor" in folded:
        return "Бакалавриат"
    if "магистр" in folded or "master" in folded:
        return "Магистратура"
    if "аспирант" in folded or "postgraduate" in folded:
        return "Аспирантура"
    return None


@dataclass(frozen=True, slots=True)
class StudyProgram:
    source_id: int
    level: str
    direction: str
    admission_year: int


@dataclass(frozen=True, slots=True)
class CatalogGroup:
    source_id: int
    display_name: str
    level: str
    direction: str
    admission_year: int

    @property
    def stored_direction(self) -> str:
        return join_direction(self.level, self.direction)


def join_direction(level: str, direction: str) -> str:
    return f"{level} · {direction}"


def split_direction(value: str | None) -> tuple[str, str]:
    if not value:
        return "Другое", "Без направления"
    level, separator, direction = value.partition(" · ")
    if not separator:
        return "Другое", value
    return level, direction


def direction_key(value: str) -> str:
    return hashlib.blake2s(value.encode(), digest_size=6).hexdigest()


class _ProgramCatalogParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.programs: list[StudyProgram] = []
        self._level_by_id: dict[str, str] = {}
        self._level: str | None = None
        self._heading_target: str | None = None
        self._heading_text: list[str] = []
        self._li_depth = 0
        self._direction_depth = 0
        self._direction_text: list[str] = []
        self._links: list[tuple[int, list[str]]] = []
        self._link_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and (attributes.get("href") or "").startswith(
            "#studyProgramLevel"
        ):
            self._heading_target = (attributes.get("href") or "").removeprefix("#")
            self._heading_text = []
            return
        if tag == "ul":
            self._level = self._level_by_id.get(attributes.get("id") or "")
            return
        if self._level is None:
            return
        if tag == "li":
            self._li_depth += 1
            if self._li_depth == 1:
                self._direction_text = []
                self._links = []
        if not self._li_depth:
            return
        if tag == "div" and "col-sm-5" in (attributes.get("class") or "").split():
            self._direction_depth += 1
        if tag == "a":
            match = _PROGRAM_PATH.match(attributes.get("href") or "")
            if match:
                self._link_text = []
                self._links.append((int(match.group(1)), self._link_text))

    def handle_data(self, data: str) -> None:
        if self._heading_target is not None:
            self._heading_text.append(data)
        if self._direction_depth:
            self._direction_text.append(data)
        if self._link_text is not None:
            self._link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._heading_target is not None:
            level = _supported_level("".join(self._heading_text))
            if level:
                self._level_by_id[self._heading_target] = level
            self._heading_target = None
            self._heading_text = []
        if tag == "a":
            self._link_text = None
        if tag == "div" and self._direction_depth:
            self._direction_depth -= 1
        if tag == "li" and self._li_depth:
            self._li_depth -= 1
            if self._li_depth == 0 and self._level:
                direction = " ".join("".join(self._direction_text).split())
                if direction and direction.casefold() != "образовательная программа":
                    for source_id, year_text in self._links:
                        year_value = "".join(year_text).strip()
                        if year_value.isdigit():
                            self.programs.append(
                                StudyProgram(
                                    source_id=source_id,
                                    level=self._level,
                                    direction=direction,
                                    admission_year=int(year_value),
                                )
                            )
        if tag == "ul":
            self._level = None


class _CurrentGroupsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.groups: list[tuple[int, str]] = []
        self._in_current = False
        self._li_depth = 0
        self._group_id: int | None = None
        self._name_depth = 0
        self._name_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "ul" and attributes.get("id") == "studentGroupsForCurrentYear":
            self._in_current = True
            return
        if not self._in_current:
            return
        if tag == "li":
            self._li_depth += 1
            if self._li_depth == 1:
                self._group_id = None
                self._name_text = []
        if not self._li_depth:
            return
        if tag == "div":
            match = _GROUP_PATH.search(attributes.get("onclick") or "")
            if match:
                self._group_id = int(match.group(1))
            if "col-sm-4" in (attributes.get("class") or "").split():
                self._name_depth += 1

    def handle_data(self, data: str) -> None:
        if self._name_depth:
            self._name_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._name_depth:
            self._name_depth -= 1
        if tag == "li" and self._li_depth:
            self._li_depth -= 1
            if self._li_depth == 0 and self._group_id is not None:
                name = " ".join("".join(self._name_text).split())
                if name:
                    self.groups.append((self._group_id, name))
        if tag == "ul" and self._in_current:
            self._in_current = False


def parse_study_programs(html: str) -> tuple[StudyProgram, ...]:
    parser = _ProgramCatalogParser()
    parser.feed(html)
    return tuple(parser.programs)


def parse_current_groups(html: str) -> tuple[tuple[int, str], ...]:
    parser = _CurrentGroupsParser()
    parser.feed(html)
    return tuple(parser.groups)


class GroupCatalogClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def fetch(self) -> tuple[CatalogGroup, ...]:
        base = str(self.settings.spbu_base_url).rstrip("/")
        headers = {
            "Accept": "text/html",
            "Accept-Language": "ru",
            "User-Agent": "spbu-assistant/0.1 (+self-hosted student timetable client)",
        }
        async with httpx.AsyncClient(
            timeout=self.settings.spbu_request_timeout_seconds,
            headers=headers,
            follow_redirects=True,
        ) as client:
            culture = await client.post(
                base + "/Base/SetClientCultureCookie",
                data={"clientCultureName": "ru"},
                headers={"Referer": base + "/AMCP"},
            )
            culture.raise_for_status()
            response = await client.get(base + "/AMCP")
            response.raise_for_status()
            programs = parse_study_programs(response.text)

            semaphore = asyncio.Semaphore(6)

            async def fetch_program(program: StudyProgram) -> tuple[CatalogGroup, ...]:
                async with semaphore:
                    page = await client.get(
                        base + f"/AMCP/StudyProgram/{program.source_id}"
                    )
                    page.raise_for_status()
                return tuple(
                    CatalogGroup(
                        source_id=source_id,
                        display_name=display_name,
                        level=program.level,
                        direction=program.direction,
                        admission_year=program.admission_year,
                    )
                    for source_id, display_name in parse_current_groups(page.text)
                )

            results = await asyncio.gather(
                *(fetch_program(program) for program in programs),
                return_exceptions=True,
            )

        by_source_id: dict[int, CatalogGroup] = {}
        for program, result in zip(programs, results, strict=True):
            if isinstance(result, Exception):
                logger.warning(
                    "Unable to read AMCP study programme %s: %s",
                    program.source_id,
                    type(result).__name__,
                )
                continue
            for group in result:
                by_source_id.setdefault(group.source_id, group)
        return tuple(
            sorted(
                by_source_id.values(),
                key=lambda item: (
                    LEVEL_ORDER.index(item.level),
                    item.direction.casefold(),
                    item.display_name.casefold(),
                ),
            )
        )


async def upsert_group_catalog(
    session: AsyncSession,
    catalog: tuple[CatalogGroup, ...],
) -> int:
    source_ids = [item.source_id for item in catalog]
    existing = {
        group.source_id: group
        for group in await session.scalars(
            select(StudentGroup).where(StudentGroup.source_id.in_(source_ids))
        )
    }
    now = datetime.now(UTC)
    for item in catalog:
        group = existing.get(item.source_id)
        if group is None:
            group = StudentGroup(
                source_id=item.source_id,
                display_name=item.display_name,
                direction=item.stored_direction,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            session.add(group)
            continue
        group.display_name = item.display_name
        group.direction = item.stored_direction
        group.enabled = True
        group.updated_at = now
    await session.flush()
    return len(catalog)
