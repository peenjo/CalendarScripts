#!/usr/bin/env python3

"""
convert_fit_workouts.py
Converts Garmin/FIT workout session data into an iCalendar (.ics) event.

Usage:
  python convert_fit_workouts.py <directory> [-o output.ics]

Finds the most recent zip file containing 'Workout' in its name in the given
directory, extracts it to a temporary location, processes all .fit and .fit.gz
files found inside, and creates a single .ics file containing all session events.
Duplicate events (identical start_times) are automatically filtered out.
"""

import argparse
import gzip
import io
import math
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitdecode
from icalendar import Calendar, Event


def find_most_recent_workout_zip(directory):
    """
    Find the most recent .zip file containing 'Workout' in its name
    (case-insensitive) in the given directory.
    """
    expanded_dir = os.path.expanduser(directory)
    dir_path = Path(expanded_dir)

    if not dir_path.is_dir():
        print(f"❌ Error: Directory not found: '{expanded_dir}'")
        sys.exit(1)

    matching_zips = []
    for f in dir_path.iterdir():
        if f.is_file() and f.suffix.lower() == '.zip':
            if 'workout' in f.name.lower():
                matching_zips.append(f)

    if not matching_zips:
        print(f"❌ No .zip files with 'Workout' in the name found in '{expanded_dir}'")
        sys.exit(1)

    # Sort by modification time (most recent first)
    matching_zips.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return matching_zips[0]


def extract_zip(zip_path, dest_dir):
    """
    Extract all contents of a zip file to the destination directory.
    Flattens nested directories into dest_dir.
    """
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(dest_dir)


def find_fit_files(directory):
    """
    Find all .fit and .fit.gz files in a directory (case-insensitive extension),
    including subdirectories.
    A .gz file is included only if the inner file name ends in .fit.
    """
    dir_path = Path(directory)
    all_files = [f for f in dir_path.rglob('*') if f.is_file()]

    fit_files = []
    for f in all_files:
        suffixes = [s.lower() for s in f.suffixes]
        if suffixes == ['.fit']:
            fit_files.append(f)
        elif len(suffixes) >= 2 and suffixes[-2:] == ['.fit', '.gz']:
            fit_files.append(f)

    return sorted(fit_files, key=lambda p: p.name.lower())


def get_fit_reader(fit_file_path):
    """
    Return a FitReader, handling both plain .fit and gzipped .fit.gz files.
    For .gz files, decompresses in memory and wraps in a BytesIO.
    """
    path = Path(fit_file_path)
    if path.suffix.lower() == '.gz':
        with gzip.open(fit_file_path, 'rb') as gz:
            data = gz.read()
        return fitdecode.FitReader(io.BytesIO(data))
    else:
        return fitdecode.FitReader(fit_file_path)


def extract_sessions_from_fit(fit_file_path):
    """
    Parse FIT file and extract all session records.
    Handles both plain .fit and gzipped .fit.gz files.
    Returns a list of dictionaries containing session field data.
    """
    sessions = []

    with get_fit_reader(fit_file_path) as fit:
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


def derive_default_output_path(zip_file_path, output_directory):
    """
    Derive default output file path.
    Returns zip_file_stem.ics in the output_directory.
    """
    expanded_output_dir = os.path.expanduser(output_directory)
    zip_path = Path(zip_file_path)
    output_name = zip_path.stem + '.ics'
    output_path = Path(expanded_output_dir) / output_name
    return str(output_path)


def parse_args():
    """Parse command line arguments using argparse."""
    parser = argparse.ArgumentParser(
        prog='convert_fit_workouts',
        description='Convert FIT workout files to iCalendar (.ics) format. '
                    'Finds the most recent zip file containing "Workout" in the name, '
                    'extracts it, and processes all .fit and .fit.gz files found inside. '
                    'Duplicate events are filtered.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
      Searches ~/Downloads for the most recent *Workout*.zip,
      extracts and processes it. Outputs to ~/Downloads/<zip_name>.ics

  %(prog)s ~/Garmin/Exports
      Searches ~/Garmin/Exports for the most recent *Workout*.zip,
      extracts and processes it. Outputs to ~/Garmin/Exports/<zip_name>.ics

  %(prog)s ~/Downloads -o all_workouts.ics
      Same as above, but outputs to all_workouts.ics

Note: The zip file is extracted to a temporary directory and cleaned up
      after processing. Files with .fit, .FIT, .Fit, .fit.gz, .FIT.GZ
      extensions inside the zip are all recognized. Gzipped files are
      decompressed automatically. Duplicate events (same start_time) are
      automatically filtered out.
        """
    )

    parser.add_argument(
        'directory',
        nargs='?',
        default='~/Downloads',
        help='Directory to search for the most recent *Workout*.zip file. '
             'Defaults to "~/Downloads".'
    )

    parser.add_argument(
        '-o', '--output',
        dest='output_file',
        default=None,
        help='Override output ICS file name. By default, uses the same '
             'name as the zip file with .ics extension.'
    )

    args = parser.parse_args()
    return args


def main(args):
    """Main entry point."""
    directory = args.directory
    output_file = args.output_file

    # Expand ~ to home directory
    directory = os.path.expanduser(directory)

    # Validate directory
    if not os.path.isdir(directory):
        print(f"❌ Error: Directory not found: '{directory}'")
        sys.exit(1)

    # Find the most recent zip file containing 'Workout' in the name
    zip_file = find_most_recent_workout_zip(directory)
    print(f"📦 Found zip file: {zip_file.name}")
    print(f"   Modified: {datetime.fromtimestamp(zip_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")

    # Extract to a temporary directory
    temp_dir = tempfile.mkdtemp(prefix='fit_extract_')
    print(f"📂 Extracting to temporary directory: {temp_dir}")

    try:
        extract_zip(zip_file, temp_dir)

        # Find all .fit and .fit.gz files (case-insensitive, including subdirs)
        fit_files = find_fit_files(temp_dir)

        if not fit_files:
            print(f"❌ No .fit files found inside '{zip_file.name}'")
            print("   (supports .fit, .FIT, .Fit, .fit.gz, .FIT.GZ, etc.)")
            sys.exit(1)

        # Derive output filename if not provided
        if output_file is None:
            output_file = derive_default_output_path(zip_file, directory)

        print(f"🔍 Found {len(fit_files)} FIT file(s):")
        for f in fit_files:
            # Show relative path within temp dir for readability
            rel_path = os.path.relpath(f, temp_dir)
            print(f"   • {rel_path}")
        print(f"📝 Output: {output_file}")
        print("-" * 50)

        # Create calendar
        cal = Calendar()
        cal.add('prodid', '-//FIT to iCalendar Converter//EN')
        cal.add('version', '2.0')
        cal.add('calscale', 'GREGORIAN')

        total_events = 0
        total_duplicates = 0
        seen_start_times = set()

        for fit_file in fit_files:
            rel_path = os.path.relpath(fit_file, temp_dir)
            print(f"\nProcessing: {rel_path}")

            try:
                sessions = extract_sessions_from_fit(str(fit_file))

                if not sessions:
                    print(f"   ⚠️  No session records found, skipping")
                    continue

                print(f"   ✅ Found {len(sessions)} session(s)")

                for session in sessions:
                    event, info = create_event_from_session(session)

                    start_key = info['start']
                    if start_key in seen_start_times:
                        print(f"   🔁 Skipping duplicate (start_time: {start_key})")
                        total_duplicates += 1
                        continue

                    seen_start_times.add(start_key)
                    cal.add_component(event)
                    total_events += 1

                    print(f"   • {info['title']}")
                    print(f"     Start: {info['start']}")
                    print(f"     End:   {info['end']}")
                    print(f"     Duration: {info['duration_min']} min")

            except Exception as e:
                print(f"   ❌ Error processing: {e}")

        print("\n" + "=" * 50)

        if total_events == 0:
            print("❌ No events were created from any FIT file.")
            sys.exit(1)

        with open(output_file, 'wb') as f:
            f.write(cal.to_ical())

        print(f"🎉 Created {output_file}")
        print(f"   Total events: {total_events}")
        if total_duplicates > 0:
            print(f"   Duplicates skipped: {total_duplicates}")
        print(f"   From {len(fit_files)} FIT file(s) in {zip_file.name}")

    finally:
        # Clean up the temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"🧹 Cleaned up temporary directory")


if __name__ == '__main__':
    args = parse_args()
    main(args)
