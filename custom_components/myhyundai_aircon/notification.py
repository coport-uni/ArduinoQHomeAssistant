"""Notification-based result judging for myhyundai_aircon.

Parses ``dumpsys notification --noredact`` output into per-record
text blobs for one package and judges success or failure by
substring, failure first (spec §9.2). Instead of clearing old
notifications before a run — which needs permissions ADB does not
have — the executor snapshots the record keys present at sequence
start and judges only records that appear afterwards, which serves
the same purpose: a stale result can never be mistaken for a new
one.

The parser deliberately avoids depending on the exact dumpsys
layout: a record starts at any line naming the package inside a
``NotificationRecord(`` and its blob is every following line until
the next record-ish marker, so title, text, ticker, and bigText all
land in the blob for plain substring matching. Verified against
One UI / Android 15 output on 2026-09-01.
"""

from __future__ import annotations

import re

_RECORD_MARKERS = ("NotificationRecord(", "StatusBarNotification(")
_KEY_PATTERN = re.compile(r"key=(\S+?):")
# A record blob should never legitimately need more lines than this;
# the cap keeps a format surprise from swallowing the whole dump.
_MAX_RECORD_LINES = 120

DUMPSYS_NOTIFICATION_COMMAND = "dumpsys notification --noredact 2>/dev/null"


def parse_package_records(dump: str, package: str) -> dict[str, str]:
    """Map notification record keys to their text blobs.

    Args:
        dump: Raw ``dumpsys notification --noredact`` output.
        package: Android package whose records to collect.

    Returns:
        Dict of record key (unique per posted notification) to the
        record's raw text blob.
    """
    records: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_lines
        if current_key is not None:
            records[current_key] = "\n".join(current_lines)
        current_key = None
        current_lines = []

    for line in dump.splitlines():
        is_record_start = any(m in line for m in _RECORD_MARKERS)
        if is_record_start:
            flush()
            if "NotificationRecord(" in line and package in line:
                found = _KEY_PATTERN.search(line)
                if found:
                    current_key = found.group(1)
                    current_lines = [line]
        elif current_key is not None:
            if len(current_lines) < _MAX_RECORD_LINES:
                current_lines.append(line)
            else:
                flush()
    flush()
    return records


def extract_display_text(blob: str) -> str:
    """Pull the human-readable message out of a record blob.

    Prefers ``android.text``, then ``tickerText``, then
    ``android.title``. Returns an empty string when none is found.
    """
    patterns = (
        r"android\.text=String \((.*?)\)\s*$",
        r"tickerText=(.*?)\s*$",
        r"android\.title=String \((.*?)\)\s*$",
    )
    for pattern in patterns:
        found = re.search(pattern, blob, re.MULTILINE)
        if found and found.group(1).strip():
            return found.group(1).strip()
    return ""


def judge_records(
    new_blobs: list[str],
    success_contains: list[str],
    failure_contains: list[str],
) -> str | None:
    """Judge the outcome from new notification blobs.

    Failure is checked before success (spec §9.2 rule 4), across
    all new records combined.

    Returns:
        ``"failure"`` or ``"success"``, or None when neither set of
        markers has appeared yet.
    """
    combined = "\n".join(new_blobs)
    if any(marker in combined for marker in failure_contains):
        return "failure"
    if any(marker in combined for marker in success_contains):
        return "success"
    return None
