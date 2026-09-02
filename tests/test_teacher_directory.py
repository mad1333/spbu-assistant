from app.schedule.teacher_directory import parse_teacher_links


def test_parses_teacher_links_per_schedule_event() -> None:
    html = """
    <ul>
      <li class="common-list-item row">
        <a href="/EducatorEvents/1312">Александров А.</a>
      </li>
      <li class="common-list-item row cancelled">
        <a href="/EducatorEvents/1464">Утешев А.</a>
        <a href="/EducatorEvents/1365">Калинина Е.</a>
      </li>
      <li class="navigation"><a href="/EducatorEvents/999">Не занятие</a></li>
    </ul>
    """

    events = parse_teacher_links(html)

    assert [[item.source_id for item in event] for event in events] == [
        [1312],
        [1464, 1365],
    ]
