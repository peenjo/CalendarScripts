#!/usr/bin/env python3

import argparse
import csv
import glob
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from icalendar import Calendar, Event


def read_workouts(csv_file):
    workouts = {}
    with open(csv_file, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            workout_num = row['Workout #']
            if workout_num in workouts:
                continue
            workouts[workout_num] = {
                'date': row['Date'],
                'duration_sec': int(row['Duration (sec)']),
                'name': row['Workout Name'].strip()
            }
    return workouts


def calculate_duration_minutes(seconds):
    return math.ceil(seconds / 60)


def create_calendar(workouts, cut_off_date=None):
    cal = Calendar()
    cal.add('prodid', '-//Workout Calendar//EN')
    cal.add('version', '2.0')

    for workout_num in sorted(workouts.keys(), key=int):
        data = workouts[workout_num]

        duration_min = calculate_duration_minutes(data['duration_sec'])

        if duration_min < 2:
            continue

        dt_start = datetime.strptime(data['date'], '%Y-%m-%d %H:%M:%S').replace(second=0)

        # Skip entries before the cut-off date
        if cut_off_date and dt_start < cut_off_date:
            continue

        dt_end = dt_start + timedelta(minutes=duration_min)

        uid = dt_start.isoformat(timespec='minutes') + '@strong'

        event = Event()
        event.add('uid', uid)
        event.add('dtstart', dt_start)
        event.add('dtend', dt_end)
        event.add('summary', data['name'])
        event.add('description', f'{duration_min} minutes')

        cal.add_component(event)

    return cal


def find_most_recent_strong_file(directory: str) -> str:
    """Find the most recent CSV file with 'strong' in the filename."""
    expanded_dir = os.path.expanduser(directory)

    if not os.path.isdir(expanded_dir):
        raise FileNotFoundError(f"Directory '{expanded_dir}' does not exist or is not accessible.")

    # Search for CSV files containing 'strong' (case-insensitive)
    pattern = os.path.join(expanded_dir, '*strong*.csv')
    matching_files = glob.glob(pattern, recursive=False)

    # Also try case variations
    pattern_upper = os.path.join(expanded_dir, '*Strong*.csv')
    matching_files.extend(glob.glob(pattern_upper, recursive=False))

    if not matching_files:
        raise FileNotFoundError(f"No CSV files with 'strong' found in '{expanded_dir}'.")

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


def parse_args():
    default_cut_off = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    parser = argparse.ArgumentParser(
        description='Convert Strong workout CSV export to iCalendar (.ics) file.'
    )
    parser.add_argument(
        'input_directory',
        nargs='?',
        default='~/Downloads',
        help='Path to the directory containing Strong CSV files. Defaults to "~/Downloads". '
             'Script will find the most recent file with "strong" in the name.'
    )
    parser.add_argument(
        '-o', '--output',
        dest='output_file',
        default=None,
        help='Override output .ics file path. By default, output is placed in the same '
             'directory as the input file with .ics extension.'
    )
    parser.add_argument(
        '-c', '--cut-off-date',
        dest='cut_off_date',
        default=default_cut_off,
        help=f'Skip entries before this date, in ISO format YYYY-MM-DD (default: {default_cut_off}, '
             '7 days before today).'
    )
    return parser.parse_args()


def main():
    args = parse_args()

    cut_off_date = datetime.strptime(args.cut_off_date, '%Y-%m-%d')

    try:
        input_file = find_most_recent_strong_file(args.input_directory)
        output_file = derive_output_path(input_file, args.output_file)

        print(f'Input:  {input_file}')
        print(f'Output: {output_file}')

        workouts = read_workouts(input_file)
        calendar = create_calendar(workouts, cut_off_date=cut_off_date)

        with open(output_file, 'wb') as f:
            f.write(calendar.to_ical())

        print(f'Wrote {len([e for e in calendar.walk("VEVENT")])} events to {output_file}')
        print(f'Cut-off date: {args.cut_off_date}')

    except FileNotFoundError as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f'Unexpected error: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
