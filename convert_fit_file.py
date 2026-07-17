"""
fit_to_ical.py
Converts Garmin/FIT workout session data into an iCalendar (.ics) event.

Usage:
  python fit_to_ical.py <directory> [-o output.ics]

Processes all .fit files in the given directory (case-insensitive extension)
and creates a single .ics file containing all session events.
"""

import argparse
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitdecode
from icalendar import Calendar, Event


def extract_sessions_from_fit(fit_file_path):
    """
    Parse FIT file and extract all session records.
    Returns a list of dictionaries containing session field data.
    """
    sessions = []

    with fitdecode.FitReader(fit_file_path) as fit:
        for frame in fit:
            if isinstance(frame, fitdecode.FitDataMessage):
                if frame.name == 'session':
                    session_data = {}

                    for field in frame.fields:
                        session_data[field.name] = field.value

                    sessions.append(session_data)

    return sessions


def get_session_title(session_data):
    """Extract meaningful title from session data in title case."""
    preferred_fields = ['name', 'local_description', 'sport', 'sub_sport']

    for field in preferred_fields:
        if field in session_data and session_data[field] is not None:
            value = session_data[field]
            if isinstance(value, tuple):
                value = value[0]
            # Convert to title case
            title_str = str(value)
            return title_str.title()

    return "Fitness Activity"


def calculate_duration_minutes(session_data):
    """Calculate session duration in minutes, rounded UP."""
    total_elapsed_time = session_data.get('total_elapsed_time', 0)
    if total_elapsed_time is None:
        total_elapsed_time = 0

    return math.ceil(int(total_elapsed_time) / 60)


def create_event_from_session(session_data):
    """Create a single iCalendar Event from session data."""
    title = get_session_title(session_data)
    duration_minutes = calculate_duration_minutes(session_data)

    start_time = session_data.get('start_time')

    if start_time is None:
        start_time = datetime.now(tz=timezone.utc)

    end_time = start_time + timedelta(minutes=duration_minutes)

    event = Event()
    uid = start_time.isoformat() + '@fit'
    event.add('uid', uid)
    event.add('summary', title)
    event.add('dtstart', start_time)
    event.add('dtend', end_time)
    event.add('dtstamp', datetime.now(tz=timezone.utc))
    event.add('description', str(duration_minutes) + ' minutes')

    return event, {
        'title': title,
        'start': start_time.isoformat(),
        'end': end_time.isoformat(),
        'duration_min': duration_minutes,
    }


def find_fit_files(directory):
    """Find all .fit files in a directory (case-insensitive extension matching)."""
    dir_path = Path(directory)
    # List all files and filter by extension case-insensitively
    all_files = [f for f in dir_path.iterdir() if f.is_file()]
    fit_files = [f for f in all_files if f.suffix.lower() == '.fit']
    return sorted(fit_files, key=lambda p: p.name.lower())


def derive_default_output_path(directory):
    """
    Derive default output file path.
    Returns 'fit_workouts.ics' for current directory ('.'), otherwise directory_name.ics
    """
    # Normalize the directory path
    norm_dir = os.path.normpath(directory)

    # Check if it's the current directory (., ./, or empty path equivalent)
    is_current_dir = norm_dir in ('.', './', '', '.')

    if is_current_dir:
        return 'fit_workouts.ics'
    else:
        dir_name = os.path.basename(os.path.normpath(norm_dir.rstrip('/\\')))
        if not dir_name:
            return 'fit_workouts.ics'
        return os.path.join(directory, dir_name + '.ics')


def parse_args():
    """Parse command line arguments using argparse."""
    parser = argparse.ArgumentParser(
        description='Convert FIT workout files to iCalendar (.ics) format. '
                    'Processes all .fit files in a directory (case-insensitive extension).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ./activities
      Creates: activities/activities.ics

  %(prog)s ./workouts -o all_workouts.ics
      Creates: all_workouts.ics

  %(prog)s /home/user/garmin/export --output calendar.ics
      Creates: calendar.ics

  %(prog)s .
      Creates: workouts.ics

Note: Files with .fit, .FIT, .Fit extensions are all recognized.
        """
    )

    parser.add_argument(
        'directory',
        help='Directory containing FIT files to process'
    )

    parser.add_argument(
        '-o', '--output',
        dest='output_file',
        default=None,
        help='Output ICS file name (default: directory name + .ics, or workouts.ics for current directory)'
    )

    args = parser.parse_args()
    return args


def main(args):
    """Main entry point."""
    directory = args.directory
    output_file = args.output_file

    # Validate directory
    if not os.path.isdir(directory):
        print(f"❌ Error: Directory not found: '{directory}'")
        sys.exit(1)

    # Find all .fit files (case-insensitive extension)
    fit_files = find_fit_files(directory)

    if not fit_files:
        print(f"❌ No .fit files found in '{directory}'")
        print("   (supports .fit, .FIT, .Fit, etc.)")
        sys.exit(1)

    # Derive output filename if not provided
    if output_file is None:
        output_file = derive_default_output_path(directory)

    print(f"📁 Scanning directory: {directory}")
    print(f"🔍 Found {len(fit_files)} FIT file(s):")
    for f in fit_files:
        print(f"   • {f.name}")
    print(f"📝 Output: {output_file}")
    print("-" * 50)

    # Create calendar
    cal = Calendar()
    cal.add('prodid', '-//FIT to iCalendar Converter//EN')
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')

    total_events = 0

    for fit_file in fit_files:
        print(f"\nProcessing: {fit_file.name}")

        try:
            sessions = extract_sessions_from_fit(str(fit_file))

            if not sessions:
                print(f"   ⚠️  No session records found, skipping")
                continue

            print(f"   ✅ Found {len(sessions)} session(s)")

            for session in sessions:
                event, info = create_event_from_session(session)
                cal.add_component(event)
                total_events += 1

                print(f"   • {info['title']}")
                print(f"     Start: {info['start']}")
                print(f"     End:   {info['end']}")
                print(f"     Duration: {info['duration_min']} min")

        except Exception as e:
            print(f"   ❌ Error processing: {e}")

    # Write the single ICS file with all events
    print("\n" + "=" * 50)

    if total_events == 0:
        print("❌ No events were created from any FIT file.")
        sys.exit(1)

    with open(output_file, 'wb') as f:
        f.write(cal.to_ical())

    print(f"🎉 Created {output_file}")
    print(f"   Total events: {total_events}")
    print(f"   From {len(fit_files)} FIT file(s)")


if __name__ == '__main__':
    args = parse_args()
    main(args)
