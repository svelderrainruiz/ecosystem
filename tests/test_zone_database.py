"""SL-12 add-on (ecosystem-control#83): the shared skip for tests that need the IANA zone database."""
import unittest
from unittest import mock
from zoneinfo import ZoneInfoNotFoundError

from tests import zone_database


class ZoneDatabaseSkipTests(unittest.TestCase):
    def decorated(self):
        @zone_database.requires_zone_database("Europe/Amsterdam")
        def body():
            pass
        return body

    def test_missing_database_skips_with_a_reason_naming_the_key_and_the_fix(self):
        with mock.patch.object(zone_database, "ZoneInfo", side_effect=ZoneInfoNotFoundError("x")):
            body = self.decorated()
        self.assertTrue(body.__unittest_skip__)
        self.assertIn("Europe/Amsterdam", body.__unittest_skip_why__)
        self.assertIn("tzdata", body.__unittest_skip_why__)
        with self.assertRaises(unittest.SkipTest):
            body()

    def test_present_database_leaves_the_test_function_untouched(self):
        with mock.patch.object(zone_database, "ZoneInfo", return_value=object()):
            body = self.decorated()
        self.assertFalse(hasattr(body, "__unittest_skip__"))

    def test_every_key_is_checked(self):
        def only_amsterdam(key):
            if key != "Europe/Amsterdam":
                raise ZoneInfoNotFoundError(key)
            return object()

        with mock.patch.object(zone_database, "ZoneInfo", side_effect=only_amsterdam):
            self.assertIsNone(zone_database.zone_database_gap("Europe/Amsterdam"))
            self.assertIn("America/New_York", zone_database.zone_database_gap("Europe/Amsterdam", "America/New_York"))

    def test_other_errors_are_not_swallowed(self):
        with mock.patch.object(zone_database, "ZoneInfo", side_effect=ValueError("bad key")), self.assertRaises(ValueError):
            zone_database.zone_database_gap("../x")


if __name__ == "__main__":
    unittest.main()
