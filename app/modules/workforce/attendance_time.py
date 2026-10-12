"""Attendance presentation and calendar dates in India; stored instants remain UTC."""
from datetime import timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def local_time(value):
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(IST)


def display_time(value):
    return local_time(value).strftime('%I:%M %p').lstrip('0') + ' IST' if value else None
