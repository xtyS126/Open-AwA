import importlib

from db.models import Base, EventLog
from core.event_log import EventLogger


def test_event_log_is_registered_from_db_models() -> None:
    assert EventLog.__module__ == "db.models.event_log"
    assert Base.metadata.tables["event_logs"] is EventLog.__table__


def test_event_log_services_use_the_db_model() -> None:
    event_log_module = importlib.import_module("core.event_log")

    assert event_log_module.EventLog is EventLog
    assert EventLogger.__module__ == "core.event_log"
