"""Time-zone aware calling window checker.

Uses `zoneinfo` (stdlib Python 3.9+) for timezone conversion.
Handles same-day windows (start < end). Overnight windows (end < start)
are not required for MVP and are not supported.
"""
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta


class CallingWindowChecker:
    """Check whether the current time falls within a configured calling window."""

    def _parse_window(self, tz: str, start: str, end: str):
        """Return (now, start_dt, end_dt) all in the given timezone."""
        zone = ZoneInfo(tz)
        now = datetime.now(tz=zone)
        start_h, start_m = (int(p) for p in start.split(":"))
        end_h, end_m = (int(p) for p in end.split(":"))
        start_dt = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end_dt = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        return now, start_dt, end_dt

    def is_within_window(self, tz: str, start: str, end: str) -> bool:
        """Check if current time is within the calling window.

        Args:
            tz: Timezone string e.g. "Asia/Kolkata"
            start: Start time string e.g. "09:00"
            end: End time string e.g. "18:00"

        Returns:
            True if current time is within [start, end] in the given timezone.
        """
        now, start_dt, end_dt = self._parse_window(tz, start, end)
        return start_dt <= now <= end_dt

    def get_seconds_until_window_open(self, tz: str, start: str, end: str) -> float:
        """Get seconds until the calling window opens.

        Returns 0 if already within window.
        Returns seconds until next window open time otherwise (today or tomorrow).
        """
        now, start_dt, end_dt = self._parse_window(tz, start, end)

        if start_dt <= now <= end_dt:
            return 0.0

        # If window hasn't opened yet today
        if now < start_dt:
            return (start_dt - now).total_seconds()

        # Window has already closed today — next open is tomorrow
        next_open = start_dt + timedelta(days=1)
        return (next_open - now).total_seconds()
