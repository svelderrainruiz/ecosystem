"""SL-7 time zone tests (INST-REQ-051, 052, 055)."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from installer import log
from tests.zone_database import requires_zone_database

PINNED = "15b4cacfbe7c996386b1eb343f2c80948ef4ecd101621629a52799d312eb108d"
ZONES = Path(__file__).resolve().parent.parent / "installer" / "zones.json"


class ZoneTests(unittest.TestCase):
    def test_zone_stored_by_name_only(self):
        """INST-REQ-052: the stored file holds the zone name and nothing else."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "zone.txt"
            log.store_zone(p, "Europe/Amsterdam")
            self.assertEqual(p.read_text(), "Europe/Amsterdam\n")
            self.assertEqual(log.read_zone(p, "Etc/UTC"), "Europe/Amsterdam")
            with self.assertRaises(log.UnknownZone):
                log.store_zone(p, "+01:00")
            with self.assertRaises(log.UnknownZone):
                log.store_zone(p, "")

    def test_zone_mapping_is_a_pinned_input(self):
        """INST-REQ-055, 051: hash of the table equals the pin in the code and in this test; source stated."""
        doc = json.loads(ZONES.read_text())
        canon = json.dumps(doc["zones"], sort_keys=True, separators=(",", ":"))
        self.assertEqual(hashlib.sha256(canon.encode()).hexdigest(), PINNED)
        self.assertEqual(log.ZONES_SHA256, PINNED)
        self.assertEqual(doc["sha256_of_zones"], PINNED)
        self.assertIn("CLDR", doc["source"])
        self.assertNotIn("UNVERIFIED", doc["source"] + doc["how_obtained"])
        self.assertTrue(doc["how_obtained"])
        self.assertTrue(log.load_zones())

    def test_edited_table_is_refused(self):
        """INST-REQ-055: a table that no longer matches the pin is a typed refusal."""
        doc = json.loads(ZONES.read_text())
        doc["zones"][0]["iana"] = "Etc/Other"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "z.json"
            p.write_text(json.dumps(doc))
            with self.assertRaises(log.ZoneTableError):
                log.load_zones(p)
            p.write_text("{")
            with self.assertRaises(log.ZoneTableError):
                log.load_zones(p)

    @requires_zone_database("Europe/Amsterdam")
    def test_every_listed_zone_is_known_to_the_os_and_has_a_country(self):
        """INST-REQ-051: selectable list entries all convert; the screen shows the country."""
        for z in log.load_zones():
            self.assertRegex(z["country"], r"^([A-Z]{2}|001)$")
            self.assertRegex(log.display_hhmm("2026-07-01T10:05:00+00:00", z["iana"]), r"^\d\d:\d\d$")

    def test_preselect_from_pc_and_silent_key(self):
        """INST-REQ-051: absent silent key means the PC's zone; Windows name maps with country."""
        self.assertEqual(log.windows_to_iana("W. Europe Standard Time", "NL"), "Europe/Amsterdam")
        self.assertEqual(log.windows_to_iana("W. Europe Standard Time", "DE"), "Europe/Berlin")
        self.assertEqual(log.choose_zone(None, "Europe/Paris"), "Europe/Paris")
        self.assertEqual(log.choose_zone("", "Europe/Paris"), "Europe/Paris")
        self.assertEqual(log.choose_zone("Asia/Tokyo", "Europe/Paris"), "Asia/Tokyo")
        with self.assertRaises(log.UnknownZone):
            log.windows_to_iana("Nowhere Standard Time")
        with self.assertRaises(log.UnknownZone):
            log.choose_zone("Mars/Base", "Europe/Paris")


if __name__ == "__main__":
    unittest.main()
