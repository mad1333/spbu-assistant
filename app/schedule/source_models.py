from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class EducatorReference(SourceModel):
    source_id: int = Field(alias="Item1")
    display_name: str = Field(alias="Item2")


class EventLocation(SourceModel):
    display_name: str = Field(default="", alias="DisplayName")
    latitude: float | None = Field(default=None, alias="Latitude")
    longitude: float | None = Field(default=None, alias="Longitude")
    educators: list[EducatorReference] = Field(
        default_factory=list, alias="EducatorIds"
    )


class StudyEvent(SourceModel):
    timetable_kind_code: int = Field(default=1, alias="StudyEventsTimeTableKindCode")
    start: datetime = Field(alias="Start")
    end: datetime = Field(alias="End")
    subject: str = Field(default="", alias="Subject")
    locations_display_text: str = Field(default="", alias="LocationsDisplayText")
    educators_display_text: str = Field(default="", alias="EducatorsDisplayText")
    has_educators: bool = Field(default=False, alias="HasEducators")
    is_cancelled: bool = Field(default=False, alias="IsCancelled")
    contingent_unit_name: str = Field(default="", alias="ContingentUnitName")
    time_was_changed: bool = Field(default=False, alias="TimeWasChanged")
    locations_were_changed: bool = Field(default=False, alias="LocationsWereChanged")
    educators_were_reassigned: bool = Field(
        default=False, alias="EducatorsWereReassigned"
    )
    event_locations: list[EventLocation] = Field(
        default_factory=list, alias="EventLocations"
    )
    educators: list[EducatorReference] = Field(
        default_factory=list, alias="EducatorIds"
    )


class ScheduleDay(SourceModel):
    day: datetime = Field(alias="Day")
    day_string: str = Field(default="", alias="DayString")
    events: list[StudyEvent] = Field(default_factory=list, alias="DayStudyEvents")


class GroupScheduleResponse(SourceModel):
    group_id: int = Field(alias="StudentGroupId")
    group_display_name: str = Field(alias="StudentGroupDisplayName")
    days: list[ScheduleDay] = Field(default_factory=list, alias="Days")

    @property
    def first_day(self) -> date | None:
        return min((item.day.date() for item in self.days), default=None)

    @property
    def last_day(self) -> date | None:
        return max((item.day.date() for item in self.days), default=None)


class EducatorScheduleResponse(SourceModel):
    educator_id: int = Field(alias="EducatorMasterId")
    display_name: str = Field(default="", alias="EducatorDisplayText")
    full_name: str = Field(default="", alias="EducatorLongDisplayText")
    days: list[ScheduleDay] = Field(default_factory=list, alias="EducatorEventsDays")
