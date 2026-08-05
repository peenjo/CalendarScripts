#!/usr/bin/env python3

import csv
import sys
from datetime import datetime, timedelta, timezone
from icalendar import Calendar, Event
import re
import os
import argparse
import glob
from pathlib import Path


def seconds_to_hours_minutes(raw_seconds: str, title: str):
    """Convert seconds to hours and minutes string."""
    seconds = float(raw_seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{title} {hours}h{minutes}m"


def create_description(data_row):
    """Create a detailed description of the sleep data"""
    description = f"Oura sleep data for {data_row['date']}\n"
    sleep_seconds = float(data_row['Total Sleep Duration'])

    # sleep stages (have same format)
    column_map = [
        ['Light Sleep Duration', 'Light Sleep:'],
        ['REM Sleep Duration', 'REM Sleep:'],
        ['Deep Sleep Duration', 'Deep Sleep:'],
    ]
    for m in column_map:
        description += seconds_to_hours_minutes(data_row[m[0]], m[1])
        percent = round((float(data_row[m[0]]) / sleep_seconds) * 100)
        description += f"  {percent}%\n"

    # awake time
    description += seconds_to_hours_minutes(data_row['Awake Time'], 'Awake:') + f"\n"

    # total duration
    total_seconds = sleep_seconds + float(data_row['Awake Time'])
    description += seconds_to_hours_minutes(total_seconds, 'Total Duration:') + f"\n"

    # sleep efficiency
    description += f"Sleep Efficiency: {data_row['Sleep Efficiency']}%"
    return description


def parse_iso_datetime_to_utc(dt_string):
    """Parse ISO 8601 datetime with timezone offset and convert to UTC."""
    dt_string = dt_string.strip()

    # Pattern: YYYY-MM-DDTHH:MM:SS.mmm±HH:MM
    pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.?\d*([+-])(\d{2}):(\d{2})'
    match = re.match(pattern, dt_string)

    if match:
        dt_part = match.group(1)
        sign = match.group(2)
        tz_hours = int(match.group(3))
        tz_minutes = int(match.group(4))

        # Parse base datetime (naive)
        dt = datetime.strptime(dt_part, '%Y-%m-%dT%H:%M:%S')

        # Calculate offset in minutes
        offset_minutes = tz_hours * 60 + tz_minutes
        if sign == '-':
            offset_minutes = -offset_minutes

        # Create timezone-aware datetime
        tz = timezone(timedelta(minutes=offset_minutes))
        dt = dt.replace(tzinfo=tz)

        # Convert to UTC
        dt_utc = dt.astimezone(timezone.utc)

        return dt_utc

    raise ValueError(f"Unable to parse datetime: {dt_string}")


def find_most_recent_oura_file(directory: str) -> str:
    """Find the most recent CSV file with 'oura' in the filename."""
    expanded_dir = os.path.expanduser(directory)

    if not os.path.isdir(expanded_dir):
        raise FileNotFoundError(f"Directory '{expanded_dir}' does not exist or is not accessible.")

    # Search for CSV files containing 'oura' (case-insensitive)
    pattern = os.path.join(expanded_dir, '*oura*.csv')
    matching_files = glob.glob(pattern, recursive=False)

    # Also try case variations
    pattern_upper = os.path.join(expanded_dir, '*Oura*.csv')
    matching_files.extend(glob.glob(pattern_upper, recursive=False))

    if not matching_files:
        raise FileNotFoundError(f"No CSV files with 'oura' found in '{expanded_dir}'.")

    # Remove duplicates (in case patterns matched same files)
    matching_files = list(set(matching_files))

    # Sort by modification time (most recent first)
    matching_files.sort(key=os.path.getmtime, reverse=True)

    return matching_files[0]


def derive_output_path(input_file: str, output_override: str = None) -> str:
    """Derive output path: same dir as input, same name with .ics extension."""
    if output_override:
        return output_override

    input_path = Path(input_file)
    output_name = input_path.stem + '.ics'
    output_path = input_path.parent / output_name
    return str(output_path)


def csv_to_ics(input_file: str, output_file: str):
    """Convert CSV file to iCalendar file with UTC times."""

    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found.")
        sys.exit(1)

    events_created = 0
    skipped_rows = 0

    # Create calendar object
    cal = Calendar()
    cal.add('prodid', '-//Oura Sleep Export//Sleep Schedule//EN')
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')
    cal.add('method', 'PUBLISH')
    cal.add('x-wr-calname', 'Oura Sleep Schedule')

    try:
        with open(input_file, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)

            for row_num, row in enumerate(reader, start=2):
                try:
                    # Parse datetime fields and convert to UTC
                    start_dt = parse_iso_datetime_to_utc(row['Bedtime Start'])
                    end_dt = parse_iso_datetime_to_utc(row['Bedtime End'])

                    sleep_duration_str = seconds_to_hours_minutes(row['Total Sleep Duration'], 'Asleep:')

                    # Create event
                    event = Event()
                    event.add('summary',
                              f"{sleep_duration_str}  Score: {row['Sleep Score']}  HR: {row['Lowest Resting Heart Rate']}")
                    event.add('dtstart', start_dt)
                    event.add('dtend', end_dt)
                    event.add('dtstamp', datetime.now(timezone.utc))
                    event.add('uid', f"{row['date']}@oura{row['Total Sleep Duration']}")
                    event.add('description', create_description(row))

                    cal.add_component(event)
                    events_created += 1

                except KeyError as e:
                    print(f"Row {row_num}: Missing column {e}", file=sys.stderr)
                    skipped_rows += 1
                except ValueError as e:
                    print(f"Row {row_num}: {e}", file=sys.stderr)
                    skipped_rows += 1

    except Exception as e:
        print(f"Error reading input file: {e}", file=sys.stderr)
        sys.exit(1)

    # Write iCalendar file
    try:
        with open(output_file, 'wb') as icsfile:
            icsfile.write(cal.to_ical())

        print(f"✓ Successfully created '{output_file}'")
        print(f"  • Total events: {events_created}")
        print(f"  • Skipped rows: {skipped_rows}")

    except Exception as e:
        print(f"Error writing output file: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Convert Oura sleep data CSV from a directory to an iCalendar (.ics) file.",
        epilog="Example: python convert_oura_sleep.py ~/Downloads"
    )

    parser.add_argument(
        'input_directory',
        type=str,
        nargs='?',
        default='~/Downloads',
        help='Path to the directory containing Oura CSV files. Defaults to "~/Downloads". '
             'Script will find the most recent file with "oura" in the name.'
    )

    parser.add_argument(
        '-o', '--output',
        type=str,
        default=None,
        help='Override output .ics file path. By default, output is placed in the same '
             'directory as the input file with .ics extension.'
    )

    args = parser.parse_args()

    try:
        input_file = find_most_recent_oura_file(args.input_directory)
        output_file = derive_output_path(input_file, args.output)

        print(f"Input:  {input_file}")
        print(f"Output: {output_file}")

        csv_to_ics(input_file, output_file)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()