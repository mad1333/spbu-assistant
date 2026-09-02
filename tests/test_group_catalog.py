from app.schedule.group_catalog import (
    direction_key,
    parse_current_groups,
    parse_study_programs,
    split_direction,
)


def test_parses_supported_amcp_program_levels() -> None:
    html = """
    <a href="#studyProgramLevel1">Дополнительные программы на базе бакалавриата</a>
    <ul id="studyProgramLevel1">
      <li class="common-list-item row">
        <div class="col-sm-5">Дополнительная программа</div>
        <div class="col-sm-1"><a href="/AMCP/StudyProgram/1">2026</a></div>
      </li>
    </ul>
    <a href="#studyProgramLevel4">Бакалавриат</a>
    <ul id="studyProgramLevel4">
      <li class="common-list-item row">
        <div class="col-sm-5">Большие данные и распределённая цифровая платформа</div>
        <div class="col-sm-1"><a href="/AMCP/StudyProgram/18925">2026</a></div>
        <div class="col-sm-1"><a href="/AMCP/StudyProgram/17466">2025</a></div>
      </li>
    </ul>
    """

    programs = parse_study_programs(html)

    assert [(item.source_id, item.level, item.admission_year) for item in programs] == [
        (18925, "Бакалавриат", 2026),
        (17466, "Бакалавриат", 2025),
    ]
    assert programs[0].direction == "Большие данные и распределённая цифровая платформа"


def test_parses_only_groups_for_current_academic_year() -> None:
    current_path = "/AMCP/StudentGroupEvents/Primary/474999"
    previous_path = "/AMCP/StudentGroupEvents/Primary/1"
    html = f"""
    <ul id="studentGroupsForCurrentYear">
      <li class="common-list-item row">
        <div class="tile" onclick="window.location.href='{current_path}'">
          <div class="col-sm-4">26.Б15-пу</div>
        </div>
      </li>
    </ul>
    <ul id="studentGroupsForPreviousYear">
      <li class="common-list-item row">
        <div class="tile" onclick="window.location.href='{previous_path}'">
          <div class="col-sm-4">Старая группа</div>
        </div>
      </li>
    </ul>
    """

    assert parse_current_groups(html) == ((474999, "26.Б15-пу"),)


def test_direction_helpers_are_stable() -> None:
    stored = "Бакалавриат · Большие данные"

    assert split_direction(stored) == ("Бакалавриат", "Большие данные")
    assert direction_key(stored) == direction_key(stored)
    assert len(direction_key(stored)) == 12
