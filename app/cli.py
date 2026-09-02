from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

from app.schedule.normalizer import normalize_schedule
from app.schedule.spbu_client import SpbuTimetableClient


def _date(value: str) -> date:
    return date.fromisoformat(value)


async def _fetch(args: argparse.Namespace) -> None:
    response = await SpbuTimetableClient().fetch_group_schedule(
        args.group,
        args.from_date,
        args.to_date,
    )
    lessons = normalize_schedule(response)
    payload = {
        "group_id": response.group_id,
        "group": response.group_display_name,
        "lesson_count": len(lessons),
        "lessons": [lesson.comparable_payload() for lesson in lessons],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spbu-assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)
    fetch = subparsers.add_parser(
        "fetch", help="Fetch and normalize an SPbU group schedule"
    )
    fetch.add_argument("--group", type=int, required=True)
    fetch.add_argument("--from-date", type=_date, required=True)
    fetch.add_argument("--to-date", type=_date, required=True)
    fetch.set_defaults(handler=_fetch)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(args.handler(args))


if __name__ == "__main__":
    main()
