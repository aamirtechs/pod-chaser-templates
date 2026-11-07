#!/usr/bin/env python3
"""pod-chaser-templates: chase missing PODs (proof of delivery) in
truck dispatching, with built-in follow-up templates and a small
tracker CLI.

A POD is the signed proof that a load was delivered. When the
carrier has not sent it, the dispatcher chases it, because
factoring and broker payment usually wait on the signed POD. This
tool keeps the list of missing PODs in a JSON tracker file and
renders a follow-up message for a load from a built-in template,
with placeholders filled from the tracker record.

Usage:
    python3 pod_chaser_templates.py templates
    python3 pod_chaser_templates.py add --file tracker.json \
        --load-number LD-1042 --carrier "Blue Ridge Transport" \
        --broker "Acme Brokerage" --delivery-date 2026-10-20
    python3 pod_chaser_templates.py list --file tracker.json
    python3 pod_chaser_templates.py list --file tracker.json --json
    python3 pod_chaser_templates.py list --file tracker.json --check
    python3 pod_chaser_templates.py render --file tracker.json \
        --load-number LD-1042 --template first_chase
    python3 pod_chaser_templates.py render --file tracker.json \
        --load-number LD-1042 --template urgent \
        --field dispatcher_name="Chris Blake"
    python3 pod_chaser_templates.py received --file tracker.json \
        --load-number LD-1042

Tracker JSON format:
    {"pods": [{"load_number": "LD-1042", "carrier": "Blue Ridge",
               "broker": "Acme Brokerage",
               "delivery_date": "2026-10-20", "status": "missing"}]}

A record's status is "missing" or "received". Only "missing"
records are outstanding. Days overdue is the number of days from
delivery_date to today, so a load delivered yesterday is 1 day
overdue. For tests, pass a reference date to days_overdue() or
outstanding() instead of relying on today.

Template rendering rule: a placeholder such as {load_number} is
replaced when a value is known, from the tracker record, from a
computed field such as days_overdue, or from a --field override.
A placeholder with no known value is left intact in the output,
exactly as written, so the sender can see what still needs
filling in. Unknown --field keys are accepted and may fill a
placeholder of the same name. --field overrides always win over
tracker values.

The --check flag on the list command exits 1 when any
outstanding POD is more than --overdue-days days overdue
(default 3), and exits 0 otherwise, so it works as a gate in a
script. It still prints the list first.
"""

import argparse
import json
import os
import re
import sys
from datetime import date

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

TEMPLATES = {
    "first_chase": (
        "Subject: POD needed for load {load_number} delivered {delivery_date}\n"
        "\n"
        "Hi {carrier_name},\n"
        "\n"
        "We are missing the signed proof of delivery for load "
        "{load_number}, delivered on {delivery_date} for {broker_name}. "
        "Could you please send the signed POD at your earliest "
        "convenience?\n"
        "\n"
        "Thank you,\n"
        "{dispatcher_name}"
    ),
    "second_chase": (
        "Subject: Second request: POD still missing for load {load_number}\n"
        "\n"
        "Hi {carrier_name},\n"
        "\n"
        "This is a second request for the signed proof of delivery "
        "for load {load_number}, delivered on {delivery_date} for "
        "{broker_name}. It is now {days_overdue} days past delivery "
        "and we still do not have the POD on file. Please send it "
        "today so payment is not delayed.\n"
        "\n"
        "Thank you,\n"
        "{dispatcher_name}"
    ),
    "urgent": (
        "Subject: Urgent: POD overdue for load {load_number} - "
        "escalation\n"
        "\n"
        "Hi {carrier_name},\n"
        "\n"
        "The signed proof of delivery for load {load_number}, "
        "delivered on {delivery_date} for {broker_name}, is now "
        "{days_overdue} days overdue. This is an escalation. "
        "Payment for this load cannot move forward without the "
        "signed POD. Please send it today, or let us know right "
        "away if there is a problem with the delivery paperwork.\n"
        "\n"
        "Thank you,\n"
        "{dispatcher_name}"
    ),
    "factoring_deadline": (
        "Subject: POD needed before factoring deadline: load "
        "{load_number}\n"
        "\n"
        "Hi {carrier_name},\n"
        "\n"
        "We need the signed proof of delivery for load "
        "{load_number}, delivered on {delivery_date} for "
        "{broker_name}, before our factoring deadline. The load "
        "is already {days_overdue} days past delivery. If we do "
        "not receive the POD in time, funding for this load will "
        "be delayed. Please send the signed POD today.\n"
        "\n"
        "Thank you,\n"
        "{dispatcher_name}"
    ),
    "sms_first_chase": (
        "Hi {carrier_name}, this is {dispatcher_name}. We are "
        "missing the signed POD for load {load_number}, delivered "
        "{delivery_date} for {broker_name}. Could you send it "
        "over today? Thanks."
    ),
    "sms_urgent": (
        "Urgent: signed POD for load {load_number} ({delivery_date}, "
        "{broker_name}) is {days_overdue} days overdue and payment "
        "is on hold. Please send it today, {carrier_name}."
    ),
}

TEMPLATE_DESCRIPTIONS = {
    "first_chase": "Email, polite first follow-up for a missing POD.",
    "second_chase": "Email, firmer second follow-up, cites days overdue.",
    "urgent": "Email, escalation when a POD is badly overdue.",
    "factoring_deadline": "Email, chase tied to a factoring deadline.",
    "sms_first_chase": "Short SMS version of the first chase.",
    "sms_urgent": "Short SMS version of the escalation.",
}

DEFAULT_DISPATCHER = "Dispatch Team"
STATUS_MISSING = "missing"
STATUS_RECEIVED = "received"


def parse_delivery_date(text):
    """Parse a YYYY-MM-DD date, raising ValueError on bad input."""
    parts = text.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(
            f"delivery_date must be YYYY-MM-DD, got {text!r}"
        )
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise ValueError(
            f"delivery_date is not a real date: {text!r}"
        ) from None


def days_overdue(delivery_date, reference_date=None):
    """Days from delivery_date to reference_date (default today).

    A future delivery date gives a negative count, so a load
    delivered in the future is never counted as overdue.
    """
    ref = reference_date or date.today()
    if isinstance(delivery_date, str):
        delivery_date = parse_delivery_date(delivery_date)
    return (ref - delivery_date).days


def load_tracker(path):
    """Load a tracker file. Returns a list of POD records."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("pods"), list):
        return data["pods"]
    raise ValueError(
        "tracker file must be a JSON object with a 'pods' list, "
        "or a bare JSON list of records"
    )


def save_tracker(path, pods):
    """Save POD records to path in the documented tracker format."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"pods": pods}, handle, indent=2)
        handle.write("\n")


def validate_record(record):
    """Check a record has the required fields and a valid date."""
    for field in ("load_number", "carrier", "broker", "delivery_date"):
        if not record.get(field):
            raise ValueError(f"record is missing required field: {field}")
    parse_delivery_date(record["delivery_date"])
    status = record.get("status", STATUS_MISSING)
    if status not in (STATUS_MISSING, STATUS_RECEIVED):
        raise ValueError(f"unknown status: {status!r}")
    record["status"] = status
    return record


def add_pod(pods, record):
    """Add a record, rejecting a duplicate load number."""
    validate_record(record)
    for existing in pods:
        if existing["load_number"] == record["load_number"]:
            raise ValueError(
                "load_number already in tracker: "
                + record["load_number"]
            )
    pods.append(record)
    return pods


def mark_received(pods, load_number):
    """Mark a load received. Returns True, or False if already
    received. Raises ValueError when the load is not found."""
    for record in pods:
        if record["load_number"] == load_number:
            if record["status"] == STATUS_RECEIVED:
                return False
            record["status"] = STATUS_RECEIVED
            return True
    raise ValueError(f"load not found in tracker: {load_number}")


def outstanding(pods, reference_date=None):
    """Outstanding (missing) records, most overdue first.

    Sort key is days overdue descending, then load number
    ascending, so the order is stable when two loads share a
    delivery date.
    """
    ref = reference_date or date.today()
    open_pods = [p for p in pods if p.get("status") != STATUS_RECEIVED]
    return sorted(
        open_pods,
        key=lambda p: (-days_overdue(p["delivery_date"], ref),
                       p["load_number"]),
    )


def record_values(record, reference_date=None):
    """Placeholder values for a record, including computed fields."""
    return {
        "load_number": record["load_number"],
        "carrier_name": record.get("carrier", ""),
        "broker_name": record.get("broker", ""),
        "delivery_date": record.get("delivery_date", ""),
        "days_overdue": str(
            days_overdue(record["delivery_date"], reference_date)
        ),
        "status": record.get("status", STATUS_MISSING),
    }


def render_template(name, values):
    """Render a template. Unknown placeholders are left intact.

    Raises ValueError for an unknown template name.
    """
    if name not in TEMPLATES:
        raise ValueError(f"unknown template: {name!r}")
    template = TEMPLATES[name]

    def replace(match):
        key = match.group(1)
        if key in values:
            return str(values[key])
        return match.group(0)

    return PLACEHOLDER_RE.sub(replace, template)


def parse_fields(field_args):
    """Parse --field key=value pairs into a dict."""
    values = {}
    for item in field_args or []:
        if "=" not in item:
            raise ValueError(
                f"--field must be key=value, got {item!r}"
            )
        key, value = item.split("=", 1)
        if not key:
            raise ValueError("--field key must not be empty")
        values[key] = value
    return values


def render_for_record(name, record, overrides=None,
                      reference_date=None):
    """Render a template for one tracker record.

    Overrides from --field win over tracker values, including the
    computed days_overdue value.
    """
    values = record_values(record, reference_date)
    values.update(overrides or {})
    return render_template(name, values)


def list_report(pods, reference_date=None, overdue_days=3):
    """Build the list report dict for outstanding PODs."""
    ref = reference_date or date.today()
    rows = []
    for record in outstanding(pods, ref):
        overdue = days_overdue(record["delivery_date"], ref)
        rows.append({
            "load_number": record["load_number"],
            "carrier": record.get("carrier", ""),
            "broker": record.get("broker", ""),
            "delivery_date": record.get("delivery_date", ""),
            "days_overdue": overdue,
            "status": record.get("status", STATUS_MISSING),
        })
    has_overdue = any(r["days_overdue"] > overdue_days for r in rows)
    return {
        "outstanding": len(rows),
        "overdue_days_threshold": overdue_days,
        "any_overdue_past_threshold": has_overdue,
        "pods": rows,
    }


def render_list_text(report):
    lines = []
    lines.append(f"Outstanding PODs: {report['outstanding']}")
    if not report["pods"]:
        lines.append("None. No PODs are outstanding.")
        return "\n".join(lines)
    for pod in report["pods"]:
        lines.append(
            f"  {pod['load_number']}: {pod['carrier']} for "
            f"{pod['broker']}, delivered {pod['delivery_date']}, "
            f"{pod['days_overdue']} days overdue"
        )
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Chase missing PODs: track them and render "
        "follow-up messages from built-in templates."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("templates", help="list built-in templates")
    p.add_argument("--json", action="store_true",
                   help="print the template list as JSON")

    p = sub.add_parser("list", help="list outstanding PODs")
    p.add_argument("--file", required=True, help="tracker JSON file")
    p.add_argument("--json", action="store_true",
                   help="print the list as JSON")
    p.add_argument("--check", action="store_true",
                   help="exit 1 when any outstanding POD is more "
                   "than --overdue-days days overdue")
    p.add_argument("--overdue-days", type=int, default=3,
                   help="overdue threshold in days for --check "
                   "(default: 3)")

    p = sub.add_parser("add", help="record a missing POD")
    p.add_argument("--file", required=True, help="tracker JSON file")
    p.add_argument("--load-number", required=True)
    p.add_argument("--carrier", required=True)
    p.add_argument("--broker", required=True)
    p.add_argument("--delivery-date", required=True,
                   help="delivery date, YYYY-MM-DD")
    p.add_argument("--status", default=STATUS_MISSING,
                   choices=[STATUS_MISSING, STATUS_RECEIVED])

    p = sub.add_parser("received",
                       help="mark a POD as received")
    p.add_argument("--file", required=True, help="tracker JSON file")
    p.add_argument("--load-number", required=True)

    p = sub.add_parser("render",
                       help="render a template for a load")
    p.add_argument("--file", required=True, help="tracker JSON file")
    p.add_argument("--load-number", required=True)
    p.add_argument("--template", required=True,
                   choices=sorted(TEMPLATES),
                   help="template name (see templates command)")
    p.add_argument("--field", action="append", default=[],
                   help="placeholder override as key=value; "
                   "repeatable")
    p.add_argument("--json", action="store_true",
                   help="print the rendered message as JSON")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.command == "templates":
        if args.json:
            print(json.dumps(
                {name: TEMPLATE_DESCRIPTIONS[name]
                 for name in sorted(TEMPLATES)}, indent=2))
        else:
            print("Templates:")
            for name in sorted(TEMPLATES):
                print(f"  {name}: {TEMPLATE_DESCRIPTIONS[name]}")
        return 0

    if args.command == "add":
        if os.path.exists(args.file):
            try:
                pods = load_tracker(args.file)
            except (ValueError, json.JSONDecodeError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        else:
            pods = []
        record = {
            "load_number": args.load_number,
            "carrier": args.carrier,
            "broker": args.broker,
            "delivery_date": args.delivery_date,
            "status": args.status,
        }
        try:
            add_pod(pods, record)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        save_tracker(args.file, pods)
        print(f"Added missing POD: {args.load_number}")
        return 0

    try:
        pods = load_tracker(args.file)
    except FileNotFoundError:
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 2
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "list":
        report = list_report(pods, overdue_days=args.overdue_days)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(render_list_text(report))
        if args.check and report["any_overdue_past_threshold"]:
            return 1
        return 0

    if args.command == "received":
        try:
            changed = mark_received(pods, args.load_number)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        save_tracker(args.file, pods)
        if changed:
            print(f"Marked POD received: {args.load_number}")
        else:
            print(f"POD already received: {args.load_number}")
        return 0

    if args.command == "render":
        record = None
        for pod in pods:
            if pod["load_number"] == args.load_number:
                record = pod
                break
        if record is None:
            print(f"error: load not found in tracker: "
                  f"{args.load_number}", file=sys.stderr)
            return 2
        try:
            overrides = parse_fields(args.field)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if "dispatcher_name" not in overrides:
            overrides.setdefault("dispatcher_name", DEFAULT_DISPATCHER)
        message = render_for_record(args.template, record, overrides)
        if args.json:
            print(json.dumps({
                "load_number": args.load_number,
                "template": args.template,
                "message": message,
            }, indent=2))
        else:
            print(message)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
