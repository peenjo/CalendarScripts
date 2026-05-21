import csv
import sys
from datetime import datetime, timedelta, timezone
from icalendar import Calendar, Event
import re
import os
import argparse

def seconds_to_hours_minutes(raw_seconds:str, title:str):
    """Convert seconds to hours and minutes string."""
    seconds = float(raw_seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{title} {hours}h{minutes}m"

def create_description(data_row):
    """Create a description """
    description = f"Oura sleep data for {data_row['date']}\n"
    sleep_seconds = float(data_row['Total Sleep Duration'])

    column_map = [
        ['Light Sleep Duration', 'Light Sleep:'],
        ['REM Sleep Duration', 'REM Sleep:'],
        ['Deep Sleep Duration', 'Deep Sleep:'],
    ]
    for m in column_map:
        description += seconds_to_hours_minutes(data_row[m[0]], m[1])
        percent = round((float(data_row[m[0]])/sleep_seconds)*100)
        description += f"  {percent}%\n"

    description += seconds_to_hours_minutes(data_row['Awake Time'], 'Awake:') + f"\n"
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

def csv_to_ics(input_file, output_file):
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
                    
                    sleep_duration_str = seconds_to_hours_minutes(row['Total Sleep Duration'], 'Sleep:')
                    
                    # Create event
                    event = Event()
                    event.add('summary', f"{sleep_duration_str}  Score: {row['Sleep Score']}  HR: {row['Lowest Resting Heart Rate']}")
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
        description="Convert Oura sleep data CSV to an iCalendar (.ics) file.",
        epilog="Example: python convert_oura_sleep_data.py oura_data.csv my_calendar.ics"
    )
    
    parser.add_argument(
        'input_file',
        type=str,
        help='Path to the input CSV file containing sleep data.'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        default='oura_sleep_calendar.ics',
        help='Path for the output .ics file. Defaults to "oura_sleep_calendar.ics"'
    )
    
    args = parser.parse_args()
    
    csv_to_ics(args.input_file, args.output)

if __name__ == "__main__":
    main()