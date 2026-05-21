"""Contacts to birthday calendar converter."""
import argparse
from datetime import datetime, date
from icalendar import Calendar, Event
import re
import vobject
import csv
from io import StringIO


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
        
        # Write header
        writer.writeheader()
        
        for row in data_dict:
            content = row[0] # title 
            description = row[1] # ISO date string for original birthday
            date_val = row[2].strftime('%Y-%m-%d') + " 09:00" # current year birthday at 9am
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
    title: str, birthday_date: datetime, this_years_birthday: datetime
) -> Event:
    """Creates a recurring annual birthday event.
    """
    event = Event()
    event.add("summary", title)
    event.add("description", birthday_date)
    event.add("dtstart", this_years_birthday, parameters={"VALUE": "DATE"})
    event.add("rrule", {"freq": "yearly"})
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
    parser = argparse.ArgumentParser(prog='Birthday Calendar Converter', description='Converts a .vcf contacts file from Proton Mail to a birthday calendar .ics that can be imported into Proton Calendar.')
    parser.add_argument('input', type=str, help='Path to the contacts (.vcf) file.')
    parser.add_argument('output', type=str, help='Path to the output files.')

    args = parser.parse_args()

    convert(input_vcf_file_path=args.input, output_file_path=args.output)
