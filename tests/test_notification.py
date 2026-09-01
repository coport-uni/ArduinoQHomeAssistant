"""Unit tests for myhyundai_aircon notification parsing and judging.

The fixture text reproduces the One UI / Android 15 dumpsys format
observed on the real device on 2026-09-01.
"""

from custom_components.myhyundai_aircon.notification import (
    extract_display_text,
    judge_records,
    parse_package_records,
)

HYUNDAI_PKG = "com.hyundai.oneapp.kr"

ACTIVE_RECORD = (
    "    NotificationRecord(0x0add1f54: pkg=com.hyundai.oneapp.kr"
    " user=UserHandle{0} id=1529783906 tag=null importance=4"
    " key=0|com.hyundai.oneapp.kr|1529783906|null|10321:"
    " Notification(channel=fcm_default_channel flags=AUTO_CANCEL))\n"
    "      opPkg=com.hyundai.oneapp.kr\n"
    "            tickerText=공조가 켜졌습니다.\n"
    "                android.title=String (원격제어 결과 안내)\n"
    "                android.text=String (공조가 켜졌습니다.)\n"
)

OTHER_RECORD = (
    "    NotificationRecord(0x123: pkg=com.other.app"
    " user=UserHandle{0} id=5 tag=null"
    " key=0|com.other.app|5|null|100: Notification(channel=x))\n"
    "                android.text=String (공조가 켜졌습니다.)\n"
)

ARCHIVE_LINE = (
    "    StatusBarNotification(pkg=com.hyundai.oneapp.kr"
    " user=UserHandle{0} id=111 tag=null"
    " key=0|com.hyundai.oneapp.kr|111|null|10321:"
    " Notification(channel=fcm_default_channel))\n"
)

DUMP = (
    "  mNotificationList:\n"
    + ACTIVE_RECORD
    + OTHER_RECORD
    + "  mArchive=Archive (41 notifications)\n"
    + ARCHIVE_LINE
)


def test_parse_extracts_only_package_records() -> None:
    """Other packages and text-less archive lines are excluded."""
    records = parse_package_records(DUMP, HYUNDAI_PKG)
    assert list(records) == ["0|com.hyundai.oneapp.kr|1529783906|null|10321"]
    blob = records["0|com.hyundai.oneapp.kr|1529783906|null|10321"]
    assert "공조가 켜졌습니다" in blob
    assert "com.other.app" not in blob


def test_record_blob_stops_at_next_record() -> None:
    """A record's blob never swallows the following record."""
    records = parse_package_records(ACTIVE_RECORD + OTHER_RECORD, HYUNDAI_PKG)
    blob = next(iter(records.values()))
    assert "원격제어 결과 안내" in blob
    assert "com.other.app" not in blob


def test_extract_display_text_prefers_android_text() -> None:
    """android.text wins over ticker and title."""
    blob = next(iter(parse_package_records(DUMP, HYUNDAI_PKG).values()))
    assert extract_display_text(blob) == "공조가 켜졌습니다."
    assert extract_display_text("no text fields here") == ""


def test_judge_failure_before_success() -> None:
    """Spec §9.2: failure markers are checked first."""
    blobs = ["공조가 켜졌습니다. 그러나 문이 열려 실패했습니다"]
    assert judge_records(blobs, ["공조가 켜졌습니다"], ["실패"]) == "failure"
    assert judge_records(blobs, ["공조가 켜졌습니다"], []) == "success"
    assert judge_records(["무관한 알림"], ["켜짐"], ["실패"]) is None
