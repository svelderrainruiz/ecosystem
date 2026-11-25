"""Shared skip for tests that need the IANA zone database, which Windows Python lacks without the tzdata package."""
import unittest
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def zone_database_gap(*keys):
    """The reason ZoneInfo cannot load one of the keys, or None when every key loads."""
    for key in keys:
        try:
            ZoneInfo(key)
        except ZoneInfoNotFoundError:
            return "the IANA zone database has no %s (ZoneInfoNotFoundError); install the tzdata package to run this test" % key
    return None


def requires_zone_database(*keys):
    """Skip the decorated test, with the reason, when ZoneInfo cannot load a key; otherwise return the test untouched.

    A test that loops over many zones passes one well-known key: a database that only lacks some names must still fail it.
    """
    reason = zone_database_gap(*keys)
    return unittest.skipIf(reason is not None, reason)
