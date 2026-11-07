# Changelog

## 1.0.0 (2026-10-31)

- First release.
- Zero-dependency Python CLI: track missing PODs (proof of
  delivery) for truck dispatching in a JSON tracker file.
- Six built-in templates: first_chase, second_chase, urgent,
  factoring_deadline, sms_first_chase, sms_urgent, with
  placeholders for load_number, carrier_name, delivery_date,
  broker_name, and days_overdue.
- Commands: templates, list, add, received, render. List shows
  outstanding PODs most overdue first.
- `--json`, `--check`, and `--overdue-days` flags (threshold
  default 3 days); `--field key=value` overrides on render.
- Documented rendering rule: placeholders with no known value
  are left intact, never silently emptied.
- 32 passing tests.
