#!/usr/bin/env python3

"""Contacts to birthday calendar converter with Email Notifications."""
import argparse
import csv
import glob
import os
import re
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

import vobject
from icalendar import Calendar, Event, Alarm


def find_most_recent_vcf_file(directory: str) -> str:
    """Find the most recent file with a .vcf suffix in the given directory."""
    expanded_dir = os.path.expanduser(directory)

    if not os.path.isdir(expanded_dir):
        raise FileNotFoundError(f"Directory '{expanded_dir}' does not exist or is not accessible.")

    # Search for .vcf files (case-insensitive)
    pattern_lower = os.path.join(expanded_dir, '*.vcf')
    pattern_upper = os.path.join(expanded_dir, '*.VCF')
    matching_files = glob.glob(pattern_lower, recursive=False)
    matching_files.extend(glob.glob(pattern_upper, recursive=False))

    if not matching_files:
        raise FileNotFoundError(f"No .vcf files found in '{expanded_dir}'.")

    # Remove duplicates
    matching_files = list(set(matching_files))

    # Sort by modification time (most recent first)
    matching_files.sort(key=os.path.getmtime, reverse=True)

    return matching_files[0]


def derive_output_path(input_file: str, output_override: str = None) -> str:
    """Derive output path: same dir as input, default name 'birthday_<current_year>.'"""
    if output_override:
        return output_override

    input_path = Path(input_file)
    cy = datetime.now().year
    output_name = f"{cy}_birthdays"
    output_path = input_path.parent / output_name
    return str(output_path)


def convert_to_todoist_csv(data_dict, filename="birthdays.csv"):
    # CSV headers
    fieldnames = [
        "CONTENT", "DESCRIPTION", "DATE", "TYPE", "PRIORITY",
        "INDENT", "AUTHOR", "DATE_LANG", "TIMEZONE"
    ]

    # static info
    AUTHOR = "Eric (9837499)"
    LANGUAGE = "en"
    TIMEZONE = "US/Pacific"
    DEFAULT_PRIORITY = "1"
    DEFAULT_INDENT = "1"
    DEFAULT_TYPE = "task"

    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for row in data_dict:
            content = row[0]  # title
            description = row[1]  # ISO date string for original birthday
            date_val = row[2].strftime('%Y-%m-%d') + " 07:00"  # current year birthday at 7am
            writer.writerow({
                "CONTENT": content,
                "DESCRIPTION": description,
                "DATE": date_val,
                "TYPE": DEFAULT_TYPE,
                "PRIORITY": DEFAULT_PRIORITY,
                "INDENT": DEFAULT_INDENT,
                "AUTHOR": AUTHOR,
                "DATE_LANG": LANGUAGE,
                "TIMEZONE": TIMEZONE
            })


def generate_birthday_event(
        title: str, birthday_date: date, this_years_birthday: date
) -> Event:
    """Creates a recurring annual birthday event with email notifications.

    Adds two VALARM components for all-day events:
    1. 1 week before at 8am (6 days + 16 hours before midnight event start)
    2. 1 day before at 8am (16 hours before midnight event start)

    Note: All-day events start at 00:00 (midnight), so to trigger at 8am
    the day/week before, we need to offset by 16 hours from the previous day.
    """
    event = Event()
    event.add("summary", title)
    event.add("description", birthday_date)
    # All-day event (DATE type, no time component)
    event.add("dtstart", this_years_birthday, parameters={"VALUE": "DATE"})
    event.add("rrule", {"freq": "yearly"})

    # --- Alarm 1: 1 Week Before at 8am ---
    # 6 days + 16 hours before midnight = 8am, 1 week prior
    alarm_week = Alarm()
    alarm_week.add("action", "EMAIL")
    alarm_week.add("trigger", timedelta(days=-6, hours=-16))
    alarm_week.add("description", f"Reminder: {title} is in 1 week!")
    event.add_component(alarm_week)

    # --- Alarm 2: 1 Day Before at 8am ---
    # 16 hours before midnight = 8am, 1 day prior
    alarm_day = Alarm()
    alarm_day.add("action", "EMAIL")
    alarm_day.add("trigger", timedelta(hours=-16))
    alarm_day.add("description", f"Reminder: {title} is tomorrow!")
    event.add_component(alarm_day)

    return event


def convert(
        input_vcf_file_path: str, output_file_path: str, event_title: str = "BDay"
):
    """Converts a .vcf contacts file from Proton Mail to a birthday calendar
    .ics that can be imported into Proton Calendar.

    Args:
        input_vcf_file_path (str): Path to the contacts file.
        output_file_path (str): Path to the output .ics file.
        event_title (str, optional): Text that will be added to the name in
            the event title. Defaults to "BDay".

    Raises:
        Exception: If the date does not match expectations.
    """

    birthdays = Calendar()
    birthdays.add("prodid", "-//Lumo Birthday Converter//")
    birthdays.add("version", "2.0")

    with open(file=input_vcf_file_path, mode="r", encoding="utf-8") as vcf_file:
        data = vcf_file.read()
        addressbook = vobject.readComponents(data)
        bday_list = []

        while (entry := next(addressbook, None)) is not None:
            if "fn" not in entry.contents:
                continue
            name = entry.contents["fn"][0].value
            if "bday" in entry.contents:
                birthday_string = entry.contents["bday"][0].value
                age = None
                if "." in birthday_string:
                    birthday_object = datetime.strptime(
                        birthday_string, "%d.%m."
                    ).date()
                    birthday_object = birthday_object.replace(year=date.today().year)
                    print(
                        f"Fixed date without year: {birthday_string} -> {birthday_object}"
                    )
                    age = None
                elif birthday_string.isdigit() and len(birthday_string) == 2 + 2 + 4:
                    birthday_object = datetime.strptime(
                        birthday_string, "%Y%m%d"
                    ).date()
                    print(birthday_object)
                    age = date.today().year - birthday_object.year
                elif re.match(r'--\d{2}\d{2}', birthday_string):
                    birthday_object = datetime.strptime(birthday_string, "--%m%d").date()
                    birthday_object = birthday_object.replace(year=date.today().year)
                    print(
                        f"Fixed date without year: {birthday_string} -> {birthday_object}"
                    )
                    age = None

                else:
                    raise Exception(f"Date {birthday_string} not implemented")

                title = f"{name} BDday ({age})"
                this_years_birthday = birthday_object.replace(year=date.today().year)
                event = generate_birthday_event(
                    title=title,
                    birthday_date=birthday_object,
                    this_years_birthday=this_years_birthday
                )

                bday_list.append([title, birthday_object, this_years_birthday])
                print(event.get(key="SUMMARY"))
                birthdays.add_component(event)

            convert_to_todoist_csv(bday_list, filename=output_file_path + '.csv')

            with open(output_file_path + '.ics', "wb") as ics_file:
                ics_file.write(birthdays.to_ical())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog='Birthday Calendar Converter',
        description='Converts a .vcf contacts file from Proton Mail to a birthday '
                    'calendar .ics that can be imported into Proton Calendar.'
    )
    parser.add_argument(
        'input_directory',
        type=str,
        nargs='?',
        default='~/Downloads',
        help='Path to the directory containing .vcf files. Defaults to "~/Downloads". '
             'Script will find the most recent file with a .vcf suffix.'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        default=None,
        help='Override output file path (without extension). By default, output is '
             'named "birthday_<current_year>" in the same directory as the input file. '
             'Both .ics and .csv files are generated.'
    )

    args = parser.parse_args()

    try:
        input_file = find_most_recent_vcf_file(args.input_directory)
        output_base = derive_output_path(input_file, args.output)
        current_year = datetime.now().year

        print(f"Input:  {input_file}")
        print(f"Output: {output_base}.ics / {output_base}.csv")

        convert(input_vcf_file_path=input_file, output_file_path=output_base)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)
