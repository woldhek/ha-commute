#!/usr/bin/env python3
"""Play a commute back through the logic, from a diagnostics download.

    python3 tools/replay.py commute-diagnostics.json [--day 2026-11-20] [--every 60]

It takes the person's places from the history in the download (Home Assistant's own record of the last 36 hours),
feeds them to a fresh copy of the logic with the settings of the download, and prints what it decides, with the gaps
in the places the phone sent. `--journal` prints the journal the integration itself kept instead: what it heard and
decided when it ran. Needs nothing but Python 3.11 or newer.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent.parent / "custom_components" / "commute" / "logic.py"
spec = importlib.util.spec_from_file_location("commute_logic", HERE)
L = importlib.util.module_from_spec(spec)
sys.modules["commute_logic"] = L
spec.loader.exec_module(L)

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def load(path: str) -> dict:
    data = json.loads(Path(path).read_text())
    return data.get("data", data)  # Home Assistant wraps a download in {"home_assistant": ..., "data": ...}


def hm(at: float, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(at, tz).strftime("%a %H:%M:%S")


def value_at(rows: list[dict], at: float) -> dict | None:
    """The row of an entity's history in force at a moment."""
    best = None
    for r in rows:
        if r["at"] <= at:
            best = r
        else:
            break
    return best


def print_journal(d: dict, tz: ZoneInfo) -> None:
    for e in d.get("journal", []):
        fix = e.get("fix")
        place = f"±{fix[3]}m speed={fix[4]}" if fix else "-"
        extra = " ".join(f"{k}={e[k]}" for k in ("speed", "activity", "ns_km", "ns") if k in e)
        note = f'  <- {e["note"]}' if "note" in e else ""
        print(f'{hm(e["at"], tz)}  zone={e["zone"] or "-":4}  {e["phase"]:8} {e["mode"]:8} {e["progress"]:3}%  '
              f'{place:22} why={",".join(e["why"])} {extra}{note}')


def replay(d: dict, tz: ZoneInfo, day: str | None, every: int) -> None:
    conf, zones, settings = d["config"], d["zones"], d["settings"]
    s = L.Settings(home=tuple(settings["home"]), work=tuple(settings["work"]), vehicle=settings.get("vehicle", L.TRANSIT))
    home_zone, work_zone = zones["home_zone"], zones["work_zone"]
    history = d["history"]
    person = history.get(conf["person"], [])
    source_id = next((r["attributes"].get("source") for r in reversed(person) if r["attributes"].get("source")), None)
    source = history.get(source_id, []) if source_id else []
    activity = history.get(conf.get("activity_sensor") or "", [])
    tracker = history.get(conf.get("ns_tracker") or "", [])
    days = conf.get("work_days", DAYS[:5])
    if not person:
        sys.exit("No history of the person in this download: is the recorder on, and does it keep the person?")

    def in_zone(row: dict, zone: dict, fix) -> bool:
        if zone["entity_id"] == "zone.home" and row["state"] == "home":
            return True
        if row["state"] == zone["name"]:
            return True
        return fix is not None and L.distance_m(fix.point, (zone["latitude"], zone["longitude"])) <= (zone["radius"] or 100)

    # The moments to play: every change of the person, and a tick every `every` seconds in between, as the
    # integration's own one-minute timer does.
    start, end = person[0]["at"], d.get("now", person[-1]["at"])
    if day:
        d0 = datetime.fromisoformat(day).replace(tzinfo=tz).timestamp()
        start, end = max(start, d0 - 6 * 3600), min(end, d0 + 24 * 3600)
    moments = sorted({r["at"] for r in person if start <= r["at"] <= end} | set(range(int(start), int(end), every)))
    trip = L.Trip()
    last_row = None
    prev_phase, prev_mode, prev_fix_at = None, None, None
    print(f"home {s.home}  work {s.work}  {L.distance_m(s.home, s.work) / 1000:.1f} km apart, work days {days}\n")
    for at in moments:
        row = value_at(person, at)
        if row is None:
            continue
        a = row["attributes"]
        fix = None
        changed = row is not last_row
        if changed and a.get("latitude") is not None:
            src = value_at(source, at)
            speed = (src or {}).get("attributes", {}).get("speed") if src else a.get("speed")
            fix = L.Fix(a["latitude"], a["longitude"], row["at"], a.get("gps_accuracy") or 50, speed)
        last_row = row
        zone = "home" if in_zone(row, home_zone, fix) else "work" if in_zone(row, work_zone, fix) else None
        act = value_at(activity, at)
        ns_km = None
        trk = value_at(tracker, at)
        if trk and fix and trk["attributes"].get("latitude") is not None:
            ns_km = L.distance_m(fix.point, (trk["attributes"]["latitude"], trk["attributes"]["longitude"])) / 1000
        hints = L.Hints(activity=act["state"] if act and act["state"] not in ("unknown", "unavailable") else None,
                        ns_tracker_km=ns_km)
        workday = DAYS[datetime.fromtimestamp(at, tz).weekday()] in days
        trip.update(at, s, zone, fix, workday, hints)
        if fix is not None:
            gap = "" if prev_fix_at is None else f"(+{round((fix.at - prev_fix_at) / 60)} min)"
            prev_fix_at = fix.at
            print(f'{hm(at, tz)}  place {row["state"][:12]:12} ±{round(fix.accuracy):4}m {gap:12} '
                  f'zone={zone or "-":4} {trip.phase:8} {trip.mode:8} {trip.percent():3}%  '
                  f'speed={"-" if trip.speed_kmh is None else round(trip.speed_kmh)} why={",".join(trip.why)}'
                  + (f" act={hints.activity}" if hints.activity else ""))
        if (trip.phase, trip.mode) != (prev_phase, prev_mode):
            if trip.phase != prev_phase:
                print(f"{hm(at, tz)}  ==> {prev_phase} -> {trip.phase}: {trip.note}")
            prev_phase, prev_mode = trip.phase, trip.mode


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--day", help="only this day and the night before it, as 2026-11-20")
    ap.add_argument("--every", type=int, default=60, help="seconds between the timer's ticks (60)")
    ap.add_argument("--journal", action="store_true", help="print the integration's own journal instead")
    args = ap.parse_args()
    d = load(args.file)
    tz = ZoneInfo(d.get("time_zone") or "UTC")
    if args.journal:
        print_journal(d, tz)
    else:
        replay(d, tz, args.day, args.every)


if __name__ == "__main__":
    main()
