"""SL-11 (guest-run fixes, ecosystem-control#64): service start/stop waits (INST-REQ-040, 041, 043) and the no-tzdata display
time with the PC's own daylight-saving rule (INST-REQ-052, 053, 054). Fakes only: no process, no registry, no network."""
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from installer import log, update, winsys
from installer.winsys import Result, WinSystem
from tests.test_installer_update import Base

NAME = "EcosystemRunner"


def state_text(word):
    return "STATE              : 4  %s" % word


class Script:
    """Fake sc.exe: `stop` answers from a list of codes; `query` answers from a list of state words (None = not installed)."""

    def __init__(self, stops=(0,), states=("STOPPED",), start=0):
        self.stops, self.states, self.start, self.calls = list(stops), list(states), start, []

    def __call__(self, argv):
        verb = argv[1]
        self.calls.append(verb)
        if verb == "stop":
            return Result(self.stops.pop(0) if len(self.stops) > 1 else self.stops[0])
        if verb == "start":
            return Result(self.start)
        if verb == "query":
            w = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return Result(1060) if w is None else Result(0, state_text(w))
        return Result(0)


def system(run):
    sleeps = []
    return WinSystem("C:\\ProgramData\\EcosystemRunner", run=run, sleep=sleeps.append), sleeps


class StartWaitTests(unittest.TestCase):
    def test_start_waits_for_running_040(self):
        f = Script(states=["START_PENDING", "START_PENDING", "RUNNING"])
        s, sleeps = system(f)
        s.start_service()
        self.assertEqual(f.calls, ["start", "query", "query", "query"])
        self.assertEqual(sleeps, [1, 1])

    def test_start_that_never_runs_is_a_typed_timeout(self):
        f = Script(states=["START_PENDING"])
        s, sleeps = system(f)
        with self.assertRaises(winsys.ServiceTimeout):
            s.start_service()
        self.assertEqual(len(sleeps), winsys.STATE_POLLS)

    def test_service_stopped_right_after_start_is_typed(self):
        s, _ = system(Script(states=["STOPPED"]))
        with self.assertRaises(winsys.ServiceCommandFailed):
            s.start_service()

    def test_already_running_still_confirmed(self):
        f = Script(start=1056, states=["RUNNING"])
        system(f)[0].start_service()
        self.assertEqual(f.calls, ["start", "query"])

    def test_install_cleans_up_when_start_never_runs(self):
        f = Script(states=["START_PENDING"], stops=[0])
        s, _ = system(f)
        with self.assertRaises(winsys.ServiceTimeout):
            s.install_service(NAME, "NT SERVICE\\" + NAME, s.folder)
        self.assertEqual([c for c in f.calls if c in ("stop", "delete")][-2:], ["stop", "delete"])


class StopWaitTests(unittest.TestCase):
    def test_stop_waits_for_stopped_041(self):
        f = Script(states=["STOP_PENDING", "STOPPED"])
        s, sleeps = system(f)
        s.stop_service()
        self.assertEqual(f.calls, ["stop", "query", "query"])
        self.assertEqual(sleeps, [1])

    def test_stop_retries_1061_with_backoff_then_succeeds(self):
        f = Script(stops=[1061, 1061, 0], states=["STOPPED"])
        s, sleeps = system(f)
        s.stop_service()
        self.assertEqual(f.calls.count("stop"), 3)
        self.assertEqual(sleeps, [1, 2])

    def test_stop_1061_forever_is_a_bounded_typed_error(self):
        f = Script(stops=[1061])
        s, sleeps = system(f)
        with self.assertRaises(winsys.ServiceNotStopped):
            s.stop_service()
        self.assertEqual(f.calls.count("stop"), len(winsys.STOP_RETRY_SECONDS) + 1)
        self.assertEqual(tuple(sleeps), winsys.STOP_RETRY_SECONDS)

    def test_stop_that_never_reaches_stopped_is_a_typed_timeout(self):
        s, sleeps = system(Script(states=["STOP_PENDING"]))
        with self.assertRaises(winsys.ServiceTimeout):
            s.stop_service()
        self.assertEqual(len(sleeps), winsys.STATE_POLLS)

    def test_stop_other_failure_is_typed_not_retried(self):
        f = Script(stops=[5])
        with self.assertRaises(winsys.ServiceCommandFailed):
            system(f)[0].stop_service()
        self.assertEqual(f.calls, ["stop"])

    def test_not_running_or_missing_needs_no_wait(self):
        for code in (1062, 1060):
            f = Script(stops=[code])
            system(f)[0].stop_service()
            self.assertEqual(f.calls, ["stop"])

    def test_service_gone_while_stopping_counts_as_stopped(self):
        system(Script(states=[None]))[0].stop_service()

    def test_cleanup_waits_for_the_stop_before_delete(self):
        f = Script(states=["START_PENDING"], stops=[1061, 0])
        s, _ = system(f)
        with self.assertRaises(winsys.ServiceTimeout):
            s.install_service(NAME, "NT SERVICE\\" + NAME, s.folder)
        self.assertEqual([c for c in f.calls if c in ("stop", "delete")], ["stop", "stop", "delete"])


class RollbackTests(Base):
    """A rollback never swaps program files while the service is not confirmed stopped (INST-REQ-040, 041)."""

    def test_restore_stops_before_swapping_and_refuses_when_not_stopped(self):
        self.state()
        backup = self.root / update.BACKUP
        (backup / update.PROGRAM).mkdir(parents=True)
        (backup / update.PROGRAM / "runner.exe").write_text("old")
        (backup / update.SERVICE_FILE).write_text(json.dumps({"name": NAME}))
        s, _ = system(Script(stops=[1061]))
        with unittest.mock.patch.object(update, "_replace_tree") as swap:
            with self.assertRaises(update.RestoreFailed):
                update._restore(self.root, s)
        swap.assert_not_called()
        self.assertTrue(backup.exists())


class FirstErrorTests(Base):
    """REV81: the first update error is kept, by class name only, in the result and in a RestoreFailed message."""

    def faulting(self, step, exc):
        def fault(name):
            if name == step:
                raise exc
        return fault

    def test_result_carries_the_first_error_class_for_each_step(self):
        from tests.test_installer_update import FakeSystem
        for step in ("stop", "swap", "start"):
            self.state()
            r = update.update(self.root, self.staged, "1.1.0", FakeSystem(), self.faulting(step, PermissionError("C:\\secret-path")))
            self.assertEqual((r.status, r.message, r.cause), ("restored", update.RESTORED, "PermissionError"))
            self.assertNotIn("secret-path", repr(r))

    def test_unhealthy_service_is_named(self):
        from tests.test_installer_update import FakeSystem
        self.state()
        r = update.update(self.root, self.staged, "1.1.0", FakeSystem(stays=False))
        self.assertEqual(r.cause, "UnhealthyService")

    def test_unhealthy_restore_message_names_the_original_error(self):
        from tests.test_installer_update import FakeSystem
        self.state()
        s = FakeSystem(stays=False)
        s.restore_bad = True
        with self.assertRaises(update.RestoreFailed) as c:
            update.update(self.root, self.staged, "1.1.0", s)
        self.assertIn("UnhealthyService", str(c.exception))

    def test_restore_failure_message_names_the_original_error(self):
        from tests.test_installer_update import FakeSystem

        class Stuck(FakeSystem):
            def stop_service(self):
                if self.calls.count("stop_service") >= 1:
                    raise winsys.ServiceNotStopped("x")
                super().stop_service()
        self.state()
        with self.assertRaises(update.RestoreFailed) as c:
            update.update(self.root, self.staged, "1.1.0", Stuck(), self.faulting("swap", PermissionError("C:\\secret-path")))
        self.assertIn("ServiceNotStopped", str(c.exception))
        self.assertIn("PermissionError", str(c.exception))
        self.assertNotIn("secret-path", str(c.exception))


def _st(month, dow, week, hour):
    return (0, month, dow, week, hour, 0, 0, 0)


NONE = (0,) * 8
W_EUROPE = {"bias": -60, "standard_bias": 0, "daylight_bias": -60, "daylight_start": _st(3, 0, 5, 2), "standard_start": _st(10, 0, 5, 3)}
EASTERN = {"bias": 300, "standard_bias": 0, "daylight_bias": -60, "daylight_start": _st(3, 0, 2, 2), "standard_start": _st(11, 0, 1, 2)}
SYDNEY = {"bias": -600, "standard_bias": 0, "daylight_bias": -60, "daylight_start": _st(10, 0, 1, 2), "standard_start": _st(4, 0, 1, 3)}
UTC_RULE = {"bias": 0, "standard_bias": 0, "daylight_bias": 0, "daylight_start": NONE, "standard_start": NONE}


class NoTzdataTests(unittest.TestCase):
    """The Windows-without-tzdata path simulated on Linux: no zoneinfo, the PC's own TimeZoneKeyName and registry rule."""

    def shown(self, utc, zone, key, rules, bias=None):
        def no_zone(_name):
            raise log.ZoneInfoNotFoundError(_name)
        with unittest.mock.patch.object(log, "ZoneInfo", no_zone), \
                unittest.mock.patch.object(log, "_registry_zone_key", return_value=key), \
                unittest.mock.patch.object(log, "_registry_rules", return_value=rules), \
                unittest.mock.patch.object(log, "_registry_bias", return_value=bias):
            return log.display_hhmm(utc, zone)

    def test_display_converts_across_daylight_saving_052_053(self):
        a = self.shown("2026-03-28T12:00:00+00:00", "Europe/Amsterdam", "W. Europe Standard Time", W_EUROPE)
        b = self.shown("2026-03-29T12:00:00+00:00", "Europe/Amsterdam", "W. Europe Standard Time", W_EUROPE)
        self.assertEqual((a, b), ("13:00", "14:00"))

    def test_the_change_instant_itself_054(self):
        z = ("Europe/Amsterdam", "W. Europe Standard Time", W_EUROPE)
        self.assertEqual(self.shown("2026-03-29T00:59:00+00:00", *z), "01:59")
        self.assertEqual(self.shown("2026-03-29T01:00:00+00:00", *z), "03:00")
        self.assertEqual(self.shown("2026-10-25T00:59:00+00:00", *z), "02:59")
        self.assertEqual(self.shown("2026-10-25T01:00:00+00:00", *z), "02:00")

    def test_machine_log_is_utc_and_display_is_plain_hhmm_054(self):
        with tempfile.TemporaryDirectory() as d:
            e = log.StepLog(Path(d) / "s.jsonl").record("a", "c", 0)
        self.assertTrue(e["started"].endswith("+00:00"))
        shown = self.shown(e["started"], "Europe/Amsterdam", "W. Europe Standard Time", W_EUROPE)
        self.assertRegex(shown, r"^\d\d:\d\d$")

    def test_western_zone_and_us_rule(self):
        z = ("America/New_York", "Eastern Standard Time", EASTERN)
        self.assertEqual(self.shown("2026-07-01T12:05:00+00:00", *z), "08:05")
        self.assertEqual(self.shown("2026-01-01T12:05:00+00:00", *z), "07:05")
        self.assertEqual(self.shown("2026-03-08T06:59:00+00:00", *z), "01:59")
        self.assertEqual(self.shown("2026-03-08T07:00:00+00:00", *z), "03:00")
        self.assertEqual(self.shown("2026-11-01T05:59:00+00:00", *z), "01:59")
        self.assertEqual(self.shown("2026-11-01T06:00:00+00:00", *z), "01:00")

    def test_southern_hemisphere_rule(self):
        z = ("Australia/Sydney", "AUS Eastern Standard Time", SYDNEY)
        if not any(r["windows"] == z[1] and r["iana"] == z[0] for r in log.load_zones()):
            self.skipTest("zone not in the pinned subset")
        self.assertEqual(self.shown("2026-01-01T00:00:00+00:00", *z), "11:00")
        self.assertEqual(self.shown("2026-07-01T00:00:00+00:00", *z), "10:00")

    def test_zone_without_daylight_saving(self):
        self.assertEqual(self.shown("2026-07-01T10:05:00+00:00", "Etc/UTC", "UTC", UTC_RULE), "10:05")

    def test_negative_bias_read_as_unsigned_dword_is_signed(self):
        self.assertEqual(log._signed32(4294967176), -120)
        self.assertEqual(log._signed32(300), 300)
        self.assertEqual(log._signed32(0), 0)

    def test_without_rules_the_active_bias_is_used(self):
        self.assertEqual(self.shown("2026-07-01T12:05:00+00:00", "Europe/Amsterdam", "W. Europe Standard Time", None, bias=-120), "14:05")

    def test_foreign_zone_is_still_refused(self):
        with self.assertRaises(log.UnknownZone):
            self.shown("2026-07-01T12:05:00+00:00", "America/New_York", "W. Europe Standard Time", W_EUROPE)

    def test_no_rules_and_no_bias_is_refused(self):
        with self.assertRaises(log.UnknownZone):
            self.shown("2026-07-01T12:05:00+00:00", "Europe/Amsterdam", "W. Europe Standard Time", None, bias=None)

    def test_new_year_edge_uses_local_standard_time_year(self):
        z = ("Europe/Amsterdam", "W. Europe Standard Time", W_EUROPE)
        self.assertEqual(self.shown("2026-12-31T23:30:00+00:00", *z), "00:30")
        self.assertEqual(self.shown("2027-01-01T00:30:00+00:00", *z), "01:30")
        s = ("Australia/Sydney", "AUS Eastern Standard Time", SYDNEY)
        self.assertEqual(self.shown("2026-12-31T14:00:00+00:00", *s), "01:00")
        self.assertEqual(self.shown("2027-01-01T13:59:00+00:00", *s), "00:59")

    def test_year_is_taken_from_local_standard_time_not_utc(self):
        rules = {"bias": -60, "standard_bias": 0, "daylight_bias": -60, "daylight_start": _st(1, 5, 1, 0), "standard_start": _st(6, 0, 1, 3)}
        z = ("Europe/Amsterdam", "W. Europe Standard Time", rules)
        self.assertEqual(self.shown("2026-12-31T22:59:00+00:00", *z), "23:59")
        self.assertEqual(self.shown("2026-12-31T23:30:00+00:00", *z), "01:30")

    def test_nonzero_year_is_an_absolute_date_rule(self):
        import datetime as dt
        rule = (2026, 6, 0, 15, 4, 30, 0, 0)
        self.assertEqual(log._transition_minutes(2031, rule), int((dt.datetime(2026, 6, 15, 4, 30) - dt.datetime(1970, 1, 1)).total_seconds() // 60))
        rules = {"bias": 0, "standard_bias": 0, "daylight_bias": -60, "daylight_start": (2026, 6, 0, 15, 4, 0, 0, 0),
                 "standard_start": (2026, 9, 0, 15, 4, 0, 0, 0)}
        z = ("Etc/UTC", "UTC", rules)
        self.assertEqual(self.shown("2026-07-01T10:00:00+00:00", *z), "11:00")
        self.assertEqual(self.shown("2026-10-01T10:00:00+00:00", *z), "10:00")

    def test_last_week_rule_handles_five_week_months(self):
        self.assertEqual(log._transition_minutes(2026, _st(3, 0, 5, 2)),
                         int((__import__("datetime").datetime(2026, 3, 29, 2) - __import__("datetime").datetime(1970, 1, 1)).total_seconds() // 60))
        self.assertEqual(log._transition_minutes(2027, _st(3, 0, 5, 2)),
                         int((__import__("datetime").datetime(2027, 3, 28, 2) - __import__("datetime").datetime(1970, 1, 1)).total_seconds() // 60))


if __name__ == "__main__":
    unittest.main()
