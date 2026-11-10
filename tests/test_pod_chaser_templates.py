import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pod_chaser_templates import (
    TEMPLATES,
    add_pod,
    days_overdue,
    list_report,
    mark_received,
    outstanding,
    parse_fields,
    render_for_record,
    render_template,
)

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "pod_chaser_templates.py",
)

REF = date(2026, 10, 31)


def record(load="LD-1042", carrier="Blue Ridge Transport",
           broker="Acme Brokerage", delivery="2026-10-20",
           status="missing"):
    return {
        "load_number": load,
        "carrier": carrier,
        "broker": broker,
        "delivery_date": delivery,
        "status": status,
    }


def write_tracker(pods):
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"pods": pods}, handle)
    handle.close()
    return handle.name


def run_cli(args):
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True,
        text=True,
    )


class TestDaysOverdue(unittest.TestCase):
    def test_days_since_delivery(self):
        self.assertEqual(days_overdue("2026-10-20", REF), 11)

    def test_same_day_is_zero(self):
        self.assertEqual(days_overdue("2026-10-31", REF), 0)

    def test_future_delivery_is_negative(self):
        self.assertEqual(days_overdue("2026-11-05", REF), -5)


class TestTemplateRendering(unittest.TestCase):
    def test_first_chase_fills_placeholders(self):
        text = render_for_record("first_chase", record(),
                                 {"dispatcher_name": "Chris Blake"},
                                 REF)
        self.assertIn("LD-1042", text)
        self.assertIn("Blue Ridge Transport", text)
        self.assertIn("Acme Brokerage", text)
        self.assertIn("2026-10-20", text)
        self.assertNotIn("{", text)

    def test_second_chase_includes_days_overdue(self):
        text = render_for_record("second_chase", record(),
                                 {"dispatcher_name": "Chris Blake"},
                                 REF)
        self.assertIn("11 days past delivery", text)

    def test_urgent_template(self):
        text = render_for_record("urgent", record(),
                                 {"dispatcher_name": "Chris Blake"},
                                 REF)
        self.assertIn("escalation", text)
        self.assertIn("11 days overdue", text)

    def test_factoring_deadline_template(self):
        text = render_for_record("factoring_deadline", record(),
                                 {"dispatcher_name": "Chris Blake"},
                                 REF)
        self.assertIn("factoring deadline", text)
        self.assertIn("LD-1042", text)

    def test_sms_templates_are_short(self):
        for name in ("sms_first_chase", "sms_urgent"):
            text = render_for_record(name, record(),
                                     {"dispatcher_name": "Chris"},
                                     REF)
            self.assertIn("LD-1042", text)
            self.assertLess(len(text), 300)

    def test_all_templates_exist(self):
        for name in ("first_chase", "second_chase", "urgent",
                     "factoring_deadline"):
            self.assertIn(name, TEMPLATES)

    def test_missing_placeholder_left_intact(self):
        text = render_template("first_chase", {"load_number": "LD-1"})
        self.assertIn("{carrier_name}", text)
        self.assertIn("LD-1", text)

    def test_field_override_wins_over_tracker_value(self):
        text = render_for_record("first_chase", record(),
                                 {"carrier_name": "Other Carrier",
                                  "dispatcher_name": "Chris"},
                                 REF)
        self.assertIn("Other Carrier", text)
        self.assertNotIn("Blue Ridge Transport", text)

    def test_field_override_can_set_days_overdue(self):
        text = render_for_record("second_chase", record(),
                                 {"dispatcher_name": "Chris",
                                  "days_overdue": "20"},
                                 REF)
        self.assertIn("20 days past delivery", text)

    def test_unknown_template_raises(self):
        with self.assertRaises(ValueError):
            render_template("no_such_template", {})

    def test_parse_fields_bad_format_raises(self):
        with self.assertRaises(ValueError):
            parse_fields(["novalue"])


class TestTrackerLogic(unittest.TestCase):
    def test_outstanding_sorted_most_overdue_first(self):
        pods = [
            record("LD-1", delivery="2026-10-28"),
            record("LD-2", delivery="2026-10-15"),
            record("LD-3", delivery="2026-10-20"),
        ]
        ordered = [p["load_number"] for p in outstanding(pods, REF)]
        self.assertEqual(ordered, ["LD-2", "LD-3", "LD-1"])

    def test_received_excluded_from_outstanding(self):
        pods = [
            record("LD-1", status="received"),
            record("LD-2"),
        ]
        self.assertEqual(
            [p["load_number"] for p in outstanding(pods, REF)],
            ["LD-2"])

    def test_mark_received(self):
        pods = [record("LD-1")]
        self.assertTrue(mark_received(pods, "LD-1"))
        self.assertEqual(pods[0]["status"], "received")
        self.assertEqual(outstanding(pods, REF), [])

    def test_mark_received_unknown_load_raises(self):
        with self.assertRaises(ValueError):
            mark_received([record("LD-1")], "LD-999")

    def test_mark_received_twice_returns_false(self):
        pods = [record("LD-1")]
        mark_received(pods, "LD-1")
        self.assertFalse(mark_received(pods, "LD-1"))

    def test_add_duplicate_load_rejected(self):
        pods = [record("LD-1")]
        with self.assertRaises(ValueError):
            add_pod(pods, record("LD-1"))

    def test_add_bad_date_rejected(self):
        with self.assertRaises(ValueError):
            add_pod([], record("LD-9", delivery="2026-02-30"))


class TestListReport(unittest.TestCase):
    def test_min_days_keeps_only_old_pods(self):
        pods = [
            record("LD-1", delivery="2026-10-15"),
            record("LD-2", delivery="2026-10-28"),
        ]
        report = list_report(pods, REF, min_days=5)
        self.assertEqual(report["outstanding"], 1)
        self.assertEqual(report["min_days"], 5)
        self.assertEqual(
            [p["load_number"] for p in report["pods"]], ["LD-1"])

    def test_without_min_days_everything_is_kept(self):
        pods = [
            record("LD-1", delivery="2026-10-15"),
            record("LD-2", delivery="2026-10-28"),
        ]
        report = list_report(pods, REF)
        self.assertEqual(report["outstanding"], 2)
        self.assertIsNone(report["min_days"])


class TestCli(unittest.TestCase):
    def test_list_json_output_sorted(self):
        path = write_tracker([
            record("LD-1", delivery="2026-10-28"),
            record("LD-2", delivery="2026-10-15"),
            record("LD-3", delivery="2026-10-15", status="received"),
        ])
        try:
            result = run_cli(["list", "--file", path, "--json"])
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["outstanding"], 2)
        self.assertEqual(data["pods"][0]["load_number"], "LD-2")
        self.assertEqual(data["pods"][1]["load_number"], "LD-1")

    def test_check_exits_1_when_past_threshold(self):
        old = (date.today().toordinal() - 10)
        delivery = date.fromordinal(old).isoformat()
        path = write_tracker([record(delivery=delivery)])
        try:
            result = run_cli(["list", "--file", path, "--check"])
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 1)

    def test_check_exits_0_within_threshold(self):
        yesterday = date.fromordinal(
            date.today().toordinal() - 1).isoformat()
        path = write_tracker([record(delivery=yesterday)])
        try:
            result = run_cli(["list", "--file", path, "--check"])
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 0)

    def test_check_custom_threshold(self):
        three_days_ago = date.fromordinal(
            date.today().toordinal() - 3).isoformat()
        path = write_tracker([record(delivery=three_days_ago)])
        try:
            strict = run_cli(["list", "--file", path, "--check",
                              "--overdue-days", "1"])
            lenient = run_cli(["list", "--file", path, "--check",
                               "--overdue-days", "30"])
        finally:
            os.unlink(path)
        self.assertEqual(strict.returncode, 1)
        self.assertEqual(lenient.returncode, 0)

    def test_check_exits_0_when_none_outstanding(self):
        path = write_tracker(
            [record(status="received")])
        try:
            result = run_cli(["list", "--file", path, "--check"])
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 0)

    def test_days_filter_shows_only_old_pods(self):
        ten_days_ago = date.fromordinal(
            date.today().toordinal() - 10).isoformat()
        one_day_ago = date.fromordinal(
            date.today().toordinal() - 1).isoformat()
        path = write_tracker([
            record("LD-1", delivery=ten_days_ago),
            record("LD-2", delivery=one_day_ago),
        ])
        try:
            result = run_cli(["list", "--file", path, "--json",
                              "--days", "5"])
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["outstanding"], 1)
        self.assertEqual(data["min_days"], 5)
        self.assertEqual(data["pods"][0]["load_number"], "LD-1")

    def test_days_filter_text_output(self):
        ten_days_ago = date.fromordinal(
            date.today().toordinal() - 10).isoformat()
        one_day_ago = date.fromordinal(
            date.today().toordinal() - 1).isoformat()
        path = write_tracker([
            record("LD-1", delivery=ten_days_ago),
            record("LD-2", delivery=one_day_ago),
        ])
        try:
            result = run_cli(["list", "--file", path, "--days", "5"])
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Outstanding PODs: 1", result.stdout)
        self.assertIn("LD-1", result.stdout)
        self.assertNotIn("LD-2", result.stdout)

    def test_days_zero_excludes_future_delivery(self):
        yesterday = date.fromordinal(
            date.today().toordinal() - 1).isoformat()
        tomorrow = date.fromordinal(
            date.today().toordinal() + 1).isoformat()
        path = write_tracker([
            record("LD-1", delivery=yesterday),
            record("LD-2", delivery=tomorrow),
        ])
        try:
            result = run_cli(["list", "--file", path, "--json",
                              "--days", "0"])
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["outstanding"], 1)
        self.assertEqual(data["pods"][0]["load_number"], "LD-1")

    def test_days_filter_applies_to_check(self):
        ten_days_ago = date.fromordinal(
            date.today().toordinal() - 10).isoformat()
        path = write_tracker([record("LD-1", delivery=ten_days_ago)])
        try:
            filtered_out = run_cli(["list", "--file", path, "--check",
                                    "--days", "30"])
            filtered_in = run_cli(["list", "--file", path, "--check",
                                   "--days", "5"])
        finally:
            os.unlink(path)
        self.assertEqual(filtered_out.returncode, 0)
        self.assertEqual(filtered_in.returncode, 1)

    def test_add_and_received_cli_round_trip(self):
        handle = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False)
        handle.close()
        path = handle.name
        os.unlink(path)
        try:
            added = run_cli(["add", "--file", path,
                             "--load-number", "LD-77",
                             "--carrier", "Test Carrier",
                             "--broker", "Test Broker",
                             "--delivery-date", "2026-10-20"])
            self.assertEqual(added.returncode, 0)
            listed = run_cli(["list", "--file", path, "--json"])
            self.assertEqual(json.loads(listed.stdout)["outstanding"], 1)
            done = run_cli(["received", "--file", path,
                            "--load-number", "LD-77"])
            self.assertEqual(done.returncode, 0)
            listed = run_cli(["list", "--file", path, "--json"])
            self.assertEqual(json.loads(listed.stdout)["outstanding"], 0)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_render_cli_fills_placeholders(self):
        path = write_tracker([record()])
        try:
            result = run_cli(["render", "--file", path,
                              "--load-number", "LD-1042",
                              "--template", "first_chase",
                              "--field", "dispatcher_name=Chris Blake"])
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Blue Ridge Transport", result.stdout)
        self.assertIn("Chris Blake", result.stdout)
        self.assertNotIn("{carrier_name}", result.stdout)

    def test_render_cli_json_output(self):
        path = write_tracker([record()])
        try:
            result = run_cli(["render", "--file", path,
                              "--load-number", "LD-1042",
                              "--template", "sms_first_chase",
                              "--field", "dispatcher_name=Chris",
                              "--json"])
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["template"], "sms_first_chase")
        self.assertIn("LD-1042", data["message"])

    def test_templates_command_lists_all(self):
        result = run_cli(["templates"])
        self.assertEqual(result.returncode, 0)
        for name in ("first_chase", "second_chase", "urgent",
                     "factoring_deadline"):
            self.assertIn(name, result.stdout)

    def test_list_missing_file_exits_2(self):
        result = run_cli(["list", "--file",
                          "/tmp/does-not-exist-pod-chaser.json"])
        self.assertEqual(result.returncode, 2)

    def test_render_unknown_load_exits_2(self):
        path = write_tracker([record()])
        try:
            result = run_cli(["render", "--file", path,
                              "--load-number", "LD-999",
                              "--template", "first_chase"])
        finally:
            os.unlink(path)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
