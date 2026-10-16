"""Manage the Temporal Schedule that runs JobDiscoveryWorkflow (default 09:00 + 18:00 IST).

Usage:
  uv run python -m scripts.schedule_discovery upsert [--hours 9,18] [--minute 0] [--keyword K] [--location L]
  uv run python -m scripts.schedule_discovery pause --note "on leave"
  uv run python -m scripts.schedule_discovery unpause
  uv run python -m scripts.schedule_discovery trigger      # one run now
  uv run python -m scripts.schedule_discovery list
  uv run python -m scripts.schedule_discovery delete

upsert is idempotent: the schedule ID is fixed, so a second run updates the
schedule (keeping paused / unpaused) instead of creating a duplicate.
Keyword / location default to the profile's search: section.
"""

import argparse
import asyncio
from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
    ScheduleUpdateInput,
)

from app.config import settings
from app.services.profile_loader import load_profile
from app.workflows.client import connect_client
from app.workflows.ids import discovery_workflow_id
from app.workflows.job_discovery_workflow import JobDiscoveryWorkflow

SCHEDULE_ID = "discovery-schedule"
TIME_ZONE = "Asia/Kolkata"
DEFAULT_HOURS = [9, 18]

# Each run starts at a random point up to this long after the nominal time:
# the same minute every day is an easy bot signal for Naukri.
START_JITTER = timedelta(minutes=15)

# After downtime, run a missed slot only if it is at most this old; never
# fire a burst of stale runs when Temporal comes back.
CATCHUP_WINDOW = timedelta(hours=1)


def build_schedule(
    keyword: str, location: str, hours: list[int], minute: int, paused: bool = False, note: str = ""
) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            JobDiscoveryWorkflow.run,
            args=[keyword, location],
            # Temporal appends "-<scheduled time>", e.g.
            # discovery-python-backend-engineer-noida-2026-10-17T03:30:00Z
            id=discovery_workflow_id(keyword, location),
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    hour=[ScheduleRange(h) for h in hours],
                    minute=[ScheduleRange(minute)],
                    comment=f"discovery at {', '.join(f'{h:02d}:{minute:02d}' for h in hours)} IST",
                )
            ],
            time_zone_name=TIME_ZONE,
            jitter=START_JITTER,
        ),
        # SKIP: if the previous discovery is still running, this slot is dropped.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=CATCHUP_WINDOW),
        state=ScheduleState(paused=paused, note=note),
    )


async def upsert(client: Client, schedule: Schedule) -> str:
    """Create the schedule, or update it in place if it already exists."""
    try:
        await client.create_schedule(SCHEDULE_ID, schedule)
        return "created"
    except ScheduleAlreadyRunningError:
        pass

    def keep_state(update_input: ScheduleUpdateInput) -> ScheduleUpdate:
        # A config change must not silently unpause a paused schedule.
        schedule.state = update_input.description.schedule.state
        return ScheduleUpdate(schedule=schedule)

    await client.get_schedule_handle(SCHEDULE_ID).update(keep_state)
    return "updated"


def describe_times(spec: ScheduleSpec) -> str:
    """"09:00, 18:00 Asia/Kolkata (+ up to 0:15:00 jitter)" from a calendar spec."""
    times = [
        f"{hour.start:02d}:{minute.start:02d}"
        for calendar in spec.calendars
        for hour in calendar.hour
        for minute in calendar.minute
    ]
    text = ", ".join(times or spec.cron_expressions) or "no calendar"
    text += f" {spec.time_zone_name or 'UTC'}"
    return text + (f" (+ up to {spec.jitter} jitter)" if spec.jitter else "")


async def show(client: Client) -> None:
    found = False
    async for entry in await client.list_schedules():
        found = True
        print(f"- {entry.id}")

    if not found:
        print("No schedules.")
        return

    try:
        description = await client.get_schedule_handle(SCHEDULE_ID).describe()
    except Exception:
        print(f"\n{SCHEDULE_ID} does not exist. Create it with: upsert")
        return

    schedule = description.schedule
    action = schedule.action
    print(f"\n{SCHEDULE_ID}:")
    # Args come back as raw payloads; decode them with our converter.
    args = await client.data_converter.decode(action.args)
    print(f"  workflow id prefix: {action.id}  args: {args}")
    print(f"  runs at: {describe_times(schedule.spec)}")
    print(f"  overlap: {schedule.policy.overlap.name}  paused: {schedule.state.paused}  note: {schedule.state.note!r}")
    print(f"  next runs (UTC): {[t.isoformat() for t in description.info.next_action_times[:3]]}")
    recent = [a.action.workflow_id for a in description.info.recent_actions[-3:]]
    print(f"  recent runs: {recent or 'none yet'}")


async def main(args: argparse.Namespace) -> None:
    client = await connect_client()
    handle = client.get_schedule_handle(SCHEDULE_ID)

    if args.command == "upsert":
        search = load_profile(settings.PROFILE_PATH).search
        hours = [int(h) for h in args.hours.split(",")]
        schedule = build_schedule(
            args.keyword or search.keyword, args.location or search.location, hours, args.minute
        )
        print(f"{SCHEDULE_ID}: {await upsert(client, schedule)}")
        await show(client)
    elif args.command == "pause":
        await handle.pause(note=args.note)
        print(f"{SCHEDULE_ID}: paused")
    elif args.command == "unpause":
        await handle.unpause(note="unpaused via schedule_discovery")
        print(f"{SCHEDULE_ID}: unpaused")
    elif args.command == "trigger":
        await handle.trigger()
        print(f"{SCHEDULE_ID}: triggered one run (skipped if one is still running)")
    elif args.command == "delete":
        await handle.delete()
        print(f"{SCHEDULE_ID}: deleted (past runs are kept)")
    else:
        await show(client)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    upsert_parser = sub.add_parser("upsert", help="create or update the schedule")
    upsert_parser.add_argument("--hours", default=",".join(map(str, DEFAULT_HOURS)), help="IST hours, e.g. 9,18")
    upsert_parser.add_argument("--minute", type=int, default=0)
    upsert_parser.add_argument("--keyword", help="default: profile search.keyword")
    upsert_parser.add_argument("--location", help="default: profile search.location")

    pause_parser = sub.add_parser("pause", help="stop starting runs")
    pause_parser.add_argument("--note", default="paused via schedule_discovery")

    for name, text in [("unpause", "start runs again"), ("trigger", "start one run now"),
                       ("list", "show schedules and the next runs"), ("delete", "remove the schedule")]:
        sub.add_parser(name, help=text)

    args = parser.parse_args(argv)
    if args.command == "upsert":
        hours = args.hours.split(",")
        if not all(h.strip().isdigit() and 0 <= int(h) <= 23 for h in hours) or not 0 <= args.minute <= 59:
            parser.error("--hours must be 0-23 (comma separated), --minute 0-59")
    return args


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
