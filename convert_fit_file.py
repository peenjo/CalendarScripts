"""
fit_to_ical.py
Converts Garmin/FIT workout session data into an iCalendar (.ics) event.

Usage: python fit_to_ical.py your_activity.fit [-o custom_name.ics]
"""

import argparse
import math
import os
from datetime import datetime, timedelta

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
                        print(field.name, field.value)
                        session_data[field.name] = field.value

                    sessions.append(session_data)

    return sessions


def get_session_title(session_data):
    """Extract meaningful title from session data."""
    preferred_fields = ['name', 'local_description', 'sport', 'sub_sport']

    for field in preferred_fields:
        if field in session_data and session_data[field] is not None:
            value = session_data[field]
            if isinstance(value, tuple):
                value = value[0]
            return str(value)

    return "Fitness Activity"


def calculate_duration_minutes(session_data):
    """Calculate session duration in minutes, rounded UP."""
    total_elapsed_time = session_data.get('total_elapsed_time', 0)
    if total_elapsed_time is None:
        total_elapsed_time = 0

    return math.ceil(int(total_elapsed_time) / 60)


def create_ics_event(session_data, output_filename=None):
    """Create a single iCalendar event from session data."""

    title = get_session_title(session_data)
    duration_minutes = calculate_duration_minutes(session_data)

    start_time = session_data.get('start_time')
    end_time = start_time + timedelta(minutes=duration_minutes)

    # Build the iCalendar object
    cal = Calendar()
    cal.add('prodid', '-//FIT to iCalendar Converter//EN')
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')

    event = Event()
    uid = start_time.isoformat() + '@fit'
    event.add('uid', uid)
    event.add('summary', title)
    event.add('dtstart', start_time)
    event.add('dtend', end_time)
    event.add('dtstamp', datetime.utcnow())
    event.add('description', str(duration_minutes) + ' minutes')

    cal.add_component(event)

    if output_filename is None:
        safe_title = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in title)
        output_filename = f"{safe_title[:50]}.ics"

    with open(output_filename, 'wb') as f:
        f.write(cal.to_ical())

    return output_filename, {
        'title': title,
        'start': start_time.isoformat(),
        'end': end_time.isoformat(),
        'duration_min': duration_minutes,
        'output_file': output_filename
    }


def derive_output_filename(input_filepath):
    """Derive output filename by replacing extension with .ics."""
    base, ext = os.path.splitext(input_filepath)
    return base + '.ics'


def parse_args():
    """Parse command line arguments using argparse."""
    parser = argparse.ArgumentParser(
        description='Convert FIT workout files to iCalendar (.ics) format.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s activity.fit
      Creates: activity.ics
  
  %(prog)s workout.fit -o meeting.ics
      Creates: meeting.ics
  
  %(prog)s garmin_run.fit --output marathon.ics
      Creates: marathon.ics
        """
    )

    parser.add_argument(
        'fit_file',
        help='Input FIT file path (required)'
    )

    parser.add_argument(
        '-o', '--output',
        dest='output_file',
        default=None,
        help='Output ICS file name (default: input filename with .fit changed to .ics)'
    )

    args = parser.parse_args()
    return args


def main(args):
    """Main entry point."""
    fit_file_path = args.fit_file
    output_file = args.output_file

    # Validate input file
    if not os.path.exists(fit_file_path):
        print(f"❌ Error: File not found: '{fit_file_path}'")
        sys.exit(1)

    # Derive output filename if not provided
    if output_file is None:
        output_file = derive_output_filename(fit_file_path)

    print(f"📁 Reading FIT file: {fit_file_path}")
    print(f"📝 Writing to: {output_file}")
    print("-" * 50)

    sessions = extract_sessions_from_fit(fit_file_path)

    if not sessions:
        print("❌ No session records found in this FIT file.")
        sys.exit(1)

    print(f"✅ Found {len(sessions)} session(s)\n")

    created_files = []
    for idx, session in enumerate(sessions, 1):
        print(f"Session {idx}:")

        try:
            filename, info = create_ics_event(session, output_file)
            created_files.append(filename)

            print(f"   Title: {info['title']}")
            print(f"   Start: {info['start']}")
            print(f"   End:   {info['end']}")
            print(f"   Duration: {info['duration_min']} min(s)")
            print(f"   Output: {info['output_file']} ✓")

        except Exception as e:
            print(f"   ❌ Error processing: {e}")

        print()

    print("=" * 50)
    print(f"🎉 Successfully created {len(created_files)} .ics file(s)")
    for fname in created_files:
        print(f"   • {fname}")


if __name__ == '__main__':
    import sys

    args = parse_args()
    main(args)
