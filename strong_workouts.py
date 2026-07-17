import csv
import math
import argparse
from datetime import datetime, timedelta
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


def parse_args():
    parser = argparse.ArgumentParser(
        description='Convert Strong workout CSV export to iCalendar (.ics) file.'
    )
    parser.add_argument(
        'input_file',
        help='Path to the Strong CSV export file.'
    )
    parser.add_argument(
        '-o', '--output',
        dest='output_file',
        default='strong_workouts.ics',
        help='Path to the output ICS file (default: strong_workouts.ics).'
    )
    parser.add_argument(
        '-c', '--cut-off-date',
        dest='cut_off_date',
        default=None,
        help='Skip entries before this date, in ISO format YYYY-MM-DD.'
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Parse the cut-off date if provided
    cut_off_date = None
    if args.cut_off_date:
        cut_off_date = datetime.strptime(args.cut_off_date, '%Y-%m-%d')

    workouts = read_workouts(args.input_file)
    calendar = create_calendar(workouts, cut_off_date=cut_off_date)

    with open(args.output_file, 'wb') as f:
        f.write(calendar.to_ical())

    print(f'Wrote {len([e for e in calendar.walk("VEVENT")])} events to {args.output_file}')


if __name__ == '__main__':
    main()
