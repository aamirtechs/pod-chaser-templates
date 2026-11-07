# pod-chaser-templates

Chase missing PODs (proof of delivery) in truck dispatching, with
built-in follow-up templates and a small tracker CLI. No account,
no upload, no dependencies. Just Python 3 and the standard library.

A signed POD is usually what unlocks broker payment and factoring
for a load. When a carrier has not sent it, this tool keeps the
missing POD on a list, sorted by how overdue it is, and renders a
ready-to-send follow-up message for the load.

## Templates

- `first_chase`: email, polite first follow-up for a missing POD.
- `second_chase`: email, firmer second follow-up, cites days overdue.
- `urgent`: email, escalation when a POD is badly overdue.
- `factoring_deadline`: email, chase tied to a factoring deadline.
- `sms_first_chase`: short SMS version of the first chase.
- `sms_urgent`: short SMS version of the escalation.

List them with:

```sh
python3 pod_chaser_templates.py templates
```

## Usage

```sh
python3 pod_chaser_templates.py add --file tracker.json \
  --load-number LD-1042 --carrier "Blue Ridge Transport" \
  --broker "Acme Brokerage" --delivery-date 2026-10-20
python3 pod_chaser_templates.py list --file tracker.json
python3 pod_chaser_templates.py list --file tracker.json --json
python3 pod_chaser_templates.py list --file tracker.json --check
python3 pod_chaser_templates.py list --file tracker.json --check \
  --overdue-days 7
python3 pod_chaser_templates.py list --file tracker.json --days 7
python3 pod_chaser_templates.py render --file tracker.json \
  --load-number LD-1042 --template first_chase
python3 pod_chaser_templates.py render --file tracker.json \
  --load-number LD-1042 --template urgent \
  --field dispatcher_name="Chris Blake"
python3 pod_chaser_templates.py received --file tracker.json \
  --load-number LD-1042
```

`--json` on `list` or `render` prints the result as JSON.
`--check` on `list` prints the list and then exits 1 when any
outstanding POD is more than `--overdue-days` days overdue
(default 3), and exits 0 otherwise, so it works as a gate in a
script. `--days N` on `list` filters the outstanding list before
printing: only PODs at least N days overdue are shown, and the
whole report (count, `--check` gate, `--json` output) describes
the filtered list. `--field key=value` on `render` overrides a
placeholder value; it is repeatable. Without a `dispatcher_name`
override, rendered messages are signed "Dispatch Team".

## Placeholders

Templates use placeholders such as `{load_number}`,
`{carrier_name}`, `{delivery_date}`, `{broker_name}`, and
`{days_overdue}`. Values come from the tracker record, plus the
computed `{days_overdue}`. A placeholder with no known value is
left intact in the output, exactly as written, so the sender can
see what still needs filling in. This is deliberate: a missing
value never silently becomes an empty string in a message sent to
a carrier. `--field` overrides always win over tracker values,
including `{days_overdue}`.

## Overdue rule

Days overdue is the number of days from `delivery_date` to today,
so a load delivered yesterday is 1 day overdue. The list shows
only outstanding PODs (status `missing`, not `received`), most
overdue first, with ties broken by load number. A future delivery
date gives a negative count and is never counted as overdue.

## Tracker JSON format

```json
{"pods": [{"load_number": "LD-1042", "carrier": "Blue Ridge Transport", "broker": "Acme Brokerage", "delivery_date": "2026-10-20", "status": "missing"}]}
```

Each record has `load_number`, `carrier`, `broker`,
`delivery_date` (YYYY-MM-DD), and `status` (`missing` or
`received`). A bare JSON list of records is also accepted when
reading. `add` rejects a duplicate load number and an invalid
date, and exits 2. `received` exits 2 for an unknown load.
`list` and `render` exit 2 when the tracker file is missing.

## Real examples

All outputs below were captured by running the CLI on
`examples/tracker.json` on 2026-10-31. That file has two
outstanding PODs and one already received (LD-1039, so it does
not appear in the list).

Listing the outstanding PODs:

```
Outstanding PODs: 2
  LD-1042: Blue Ridge Transport for Acme Brokerage, delivered 2026-10-20, 11 days overdue
  LD-1045: Prairie Line Hauling for Acme Brokerage, delivered 2026-10-28, 3 days overdue
```

That same list with `--check` exits 1, because LD-1042 is 11 days
overdue, past the default threshold of 3 days.

Filtering that tracker to PODs at least 12 days overdue with
`--days 12` (run on 2026-11-07) leaves only LD-1042:

```
Outstanding PODs: 1
  LD-1042: Blue Ridge Transport for Acme Brokerage, delivered 2026-10-20, 18 days overdue
```

The list with `--json`:

```json
{
  "outstanding": 2,
  "overdue_days_threshold": 3,
  "any_overdue_past_threshold": true,
  "pods": [
    {
      "load_number": "LD-1042",
      "carrier": "Blue Ridge Transport",
      "broker": "Acme Brokerage",
      "delivery_date": "2026-10-20",
      "days_overdue": 11,
      "status": "missing"
    },
    {
      "load_number": "LD-1045",
      "carrier": "Prairie Line Hauling",
      "broker": "Acme Brokerage",
      "delivery_date": "2026-10-28",
      "days_overdue": 3,
      "status": "missing"
    }
  ]
}
```

Rendering the first chase for LD-1042 (also saved as
`examples/sample-rendered-message.txt`):

```
Subject: POD needed for load LD-1042 delivered 2026-10-20

Hi Blue Ridge Transport,

We are missing the signed proof of delivery for load LD-1042, delivered on 2026-10-20 for Acme Brokerage. Could you please send the signed POD at your earliest convenience?

Thank you,
Chris Blake
```

Rendering the urgent SMS for the same load:

```
Urgent: signed POD for load LD-1042 (2026-10-20, Acme Brokerage) is 11 days overdue and payment is on hold. Please send it today, Blue Ridge Transport.
```

Adding a load and marking one received (run on a copy of the
example tracker):

```
Added missing POD: LD-1050
Marked POD received: LD-1045
Outstanding PODs: 2
  LD-1042: Blue Ridge Transport for Acme Brokerage, delivered 2026-10-20, 11 days overdue
  LD-1050: Harbor Road Carriers for Summit Freight, delivered 2026-10-29, 2 days overdue
```

## Limitations

- This tool drafts messages, it does not send email or SMS. Copy
  the rendered message into your mail or messaging app.
- The whole tracker file is read into memory, so a very large
  tracker (many thousands of loads) may be slow.
- Only one status change is tracked per load: missing or
  received. There is no history of past chases per load.
- Days overdue uses the calendar date only, not business days,
  and no holidays are excluded.

## Tests

```sh
python3 -m unittest discover -s tests
```

38 tests, covering template rendering for all six templates,
missing placeholders left intact, `--field` overrides, overdue
calculation, overdue sorting, mark-received behavior, duplicate
and invalid-date rejection, `--json` output, the `--days` filter
(including with `--check`), and `--check` exit codes including a
custom threshold.

## License

MIT. See `LICENSE`.
