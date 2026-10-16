"""Discovery schedule: what it runs and when, and that upsert never duplicates."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from temporalio.client import ScheduleAlreadyRunningError, ScheduleOverlapPolicy, ScheduleState

from app.workflows.ids import discovery_workflow_id
from scripts import schedule_discovery as sd


def test_schedule_runs_discovery_twice_a_day_in_ist():
    schedule = sd.build_schedule("Python Backend Engineer", "Noida", [9, 18], 0)

    calendar = schedule.spec.calendars[0]
    assert [r.start for r in calendar.hour] == [9, 18]
    assert [r.start for r in calendar.minute] == [0]
    assert schedule.spec.time_zone_name == "Asia/Kolkata"
    assert schedule.spec.jitter == timedelta(minutes=15)

    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.policy.catchup_window == timedelta(hours=1)

    action = schedule.action
    assert action.workflow == "JobDiscoveryWorkflow"
    assert action.args == ["Python Backend Engineer", "Noida"]
    assert action.id == "discovery-python-backend-engineer-noida"
    assert action.task_queue == sd.settings.TEMPORAL_TASK_QUEUE


def test_manual_start_uses_the_same_id_prefix():
    assert discovery_workflow_id("Python Backend Engineer", "Noida") == "discovery-python-backend-engineer-noida"


class FakeClient:
    """Holds at most one schedule per id, like the Temporal server."""

    def __init__(self):
        self.schedules = {}
        self.creates = 0

    async def create_schedule(self, schedule_id, schedule):
        if schedule_id in self.schedules:
            raise ScheduleAlreadyRunningError()
        self.creates += 1
        self.schedules[schedule_id] = schedule

    def get_schedule_handle(self, schedule_id):
        client = self

        class Handle:
            async def update(self, updater):
                current = client.schedules[schedule_id]
                update_input = SimpleNamespace(description=SimpleNamespace(schedule=current))
                client.schedules[schedule_id] = updater(update_input).schedule

        return Handle()


def test_upsert_twice_updates_instead_of_duplicating():
    client = FakeClient()

    first = asyncio.run(sd.upsert(client, sd.build_schedule("Python", "Noida", [9, 18], 0)))
    second = asyncio.run(sd.upsert(client, sd.build_schedule("Python", "Pune", [10], 30)))

    assert (first, second) == ("created", "updated")
    assert client.creates == 1
    assert list(client.schedules) == [sd.SCHEDULE_ID]
    assert client.schedules[sd.SCHEDULE_ID].action.args == ["Python", "Pune"]


def test_update_keeps_a_paused_schedule_paused():
    client = FakeClient()
    client.schedules[sd.SCHEDULE_ID] = sd.build_schedule("Python", "Noida", [9], 0)
    client.schedules[sd.SCHEDULE_ID].state = ScheduleState(paused=True, note="on leave")

    asyncio.run(sd.upsert(client, sd.build_schedule("Python", "Noida", [9, 18], 0)))

    state = client.schedules[sd.SCHEDULE_ID].state
    assert (state.paused, state.note) == (True, "on leave")


@pytest.mark.parametrize("argv", [["upsert", "--hours", "25"], ["upsert", "--hours", "9,x"], ["upsert", "--minute", "60"]])
def test_bad_times_are_rejected(argv):
    with pytest.raises(SystemExit):
        sd.parse_args(argv)


def test_times_are_described_readably():
    spec = sd.build_schedule("Python", "Noida", [9, 18], 0).spec

    assert sd.describe_times(spec) == "09:00, 18:00 Asia/Kolkata (+ up to 0:15:00 jitter)"
