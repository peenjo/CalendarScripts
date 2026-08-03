#!/usr/bin/env python3

"""
summarize_workouts.py
Summarize weekly time spent on workout categories from an iCalendar (.ics) file.

Usage:
  python summarize_workouts.py <input.ics> [--cutoff-date YYYY-MM-DD]

Examples:
  python summarize_workouts.py fit_workouts.ics
  python summarize_workouts.py fit_workouts.ics --cutoff-date 2026-01-01
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from icalendar import Calendar


def get_week_start(dt):
    """
    Given a datetime, return the date of the Monday that starts its week.
    Weeks start on Monday.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None).replace(tzinfo=None)
    weekday = dt.weekday()  # Monday=0, Sunday=6
    monday = dt.date() - timedelta(days=weekday)
    return monday


def compute_duration_minutes(event):
    """
    Compute the duration of an event in minutes from DTEND - DTSTART.
    Handles both datetime (with time) and date-only events.
    """
    dtstart = event.get('dtstart')
    dtend = event.get('dtend')

    if dtstart is None or dtend is None:
        return 0

    start_val = dtstart.dt
    end_val = dtend.dt

    if isinstance(start_val, datetime) and isinstance(end_val, datetime):
        delta = end_val - start_val
        return int(delta.total_seconds() // 60)

    elif hasattr(start_val, 'toordinal') and hasattr(end_val, 'toordinal'):
        delta = end_val - start_val
        return int(delta.total_seconds() // 60) if hasattr(delta, 'total_seconds') else int(delta.days * 1440)

    return 0


def read_ics_events(ics_file_path, cut_off_date=None):
    """
    Read an ICS file and return a list of (title, week_start_date, duration_minutes) tuples.
    Events prior to cut_off_date (if provided) are ignored.
    """
    with open(ics_file_path, 'rb') as f:
        cal = Calendar.from_ical(f.read())

    events = []
    skipped = 0

    for component in cal.walk('VEVENT'):
        title = str(component.get('summary', 'Unknown'))

        dtstart = component.get('dtstart')
        if dtstart is None:
            continue

        start_dt = dtstart.dt
        if not isinstance(start_dt, datetime):
            # Date-only event, convert to datetime at midnight for week calculation
            start_dt = datetime.combine(start_dt, datetime.min.time())

        # Apply cutoff date filter
        if cut_off_date is not None:
            event_date = start_dt.date() if start_dt.tzinfo is None else start_dt.astimezone(tz=None).replace(
                tzinfo=None).date()
            if event_date < cut_off_date:
                skipped += 1
                continue

        week_start = get_week_start(start_dt)
        duration = compute_duration_minutes(component)

        events.append((title, week_start, duration))

    if skipped > 0:
        print(f"⏭️  Skipped {skipped} event(s) prior to cutoff date ({cut_off_date})\n")

    return events


def summarize_by_week(events):
    """
    Group events by week and then by category (title).
    Returns a dict: {week_start_date: {title: total_minutes}}
    Also returns grand totals per category.
    """
    weekly = defaultdict(lambda: defaultdict(int))
    category_totals = defaultdict(int)

    for title, week_start, duration in events:
        weekly[week_start][title] += duration
        category_totals[title] += duration

    return weekly, category_totals


def format_minutes(minutes):
    """Format minutes as 'Xh Ym' or 'Ym'."""
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h {mins:02d}m"
    return f"{mins}m"


def print_summary(weekly, category_totals):
    """Print the weekly summary and category totals."""
    if not weekly:
        print("No events found after filtering.")
        return

    sorted_weeks = sorted(weekly.keys())
    all_categories = sorted(category_totals.keys())

    print("=" * 70)
    print("WEEKLY WORKOUT SUMMARY")
    print("=" * 70)

    for week_start in sorted_weeks:
        week_end = week_start + timedelta(days=6)
        week_label = f"Week of {week_start.strftime('%Y-%m-%d')} ({week_start.strftime('%a')})"
        week_data = weekly[week_start]

        print(f"\n{'─' * 70}")
        print(f"📅 {week_label} – {week_end.strftime('%Y-%m-%d')} ({week_end.strftime('%a')})")
        print(f"{'─' * 70}")

        week_total = 0
        for category in all_categories:
            if category in week_data:
                minutes = week_data[category]
                week_total += minutes
                print(f"   {category:<30s} {format_minutes(minutes):>8s}")

        print(f"   {'─' * 40}")
        print(f"   {'Weekly Total':<30s} {format_minutes(week_total):>8s}")

    print(f"\n{'=' * 70}")
    print("GRAND TOTALS BY CATEGORY")
    print(f"{'=' * 70}")

    grand_total = 0
    for category in all_categories:
        minutes = category_totals[category]
        grand_total += minutes
        print(f"   {category:<30s} {format_minutes(minutes):>8s}")

    print(f"   {'─' * 40}")
    print(f"   {'Grand Total':<30s} {format_minutes(grand_total):>8s}")
    print(f"   {'Total Weeks':<30s} {len(sorted_weeks):>8}")
    print()

    num_weeks = len(sorted_weeks)
    print(f"{'=' * 70}")
    print("WEEKLY AVERAGE BY CATEGORY")
    print(f"{'=' * 70}")

    for category in all_categories:
        avg = category_totals[category] / num_weeks
        print(f"   {category:<30s} {format_minutes(int(round(avg))):>8s}/week")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Summarize weekly workout time from an iCalendar (.ics) file.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s fit_workouts.ics
  %(prog)s fit_workouts.ics --cutoff-date 2026-01-01

Duration is calculated from DTEND - DTSTART (description field ignored).
Events prior to the cutoff date are excluded.
        """
    )

    parser.add_argument(
        'ics_file',
        help='Input ICS file path'
    )

    parser.add_argument(
        '-c', '--cut-off-date',
        dest='cut_off_date',
        default=None,
        help='Skip entries before this date, in ISO format YYYY-MM-DD.'
    )

    args = parser.parse_args()

    # Parse the cutoff date string into a date object
    if args.cut_off_date is not None:
        try:
            args.cut_off_date = datetime.strptime(args.cut_off_date, '%Y-%m-%d').date()
        except ValueError:
            parser.error(f"Invalid cutoff date format: '{args.cut_off_date}'. Use YYYY-MM-DD.")

    return args


def main(args):
    """Main entry point."""
    import os

    ics_file = args.ics_file
    cut_off_date = args.cut_off_date

    if not os.path.exists(ics_file):
        print(f"❌ Error: File not found: '{ics_file}'")
        sys.exit(1)

    print(f"📁 Reading ICS file: {ics_file}")
    if cut_off_date:
        print(f"📅 Cutoff date: {cut_off_date}")
    print("-" * 70)

    events = read_ics_events(ics_file, cut_off_date)

    if not events:
        print("❌ No VEVENT entries found after filtering.")
        sys.exit(1)

    print(f"✅ Found {len(events)} event(s) after filtering\n")

    weekly, category_totals = summarize_by_week(events)
    print_summary(weekly, category_totals)


if __name__ == '__main__':
    args = parse_args()
    main(args)
