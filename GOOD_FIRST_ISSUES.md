# Good first issues

Small, testable tasks for first-time contributors. No network access needed.

1. Add a `--days` filter to the list command that shows only PODs
   at least N days overdue. Scope: add the flag, filter the
   outstanding list before printing, add CLI tests.
2. Add a `summary` command that prints counts by carrier and by
   broker, plus the single most overdue load. Scope: add the
   subcommand, reuse the existing report helpers, add tests,
   document it in the README.
3. Add an SMS length warning: when a rendered SMS template is
   longer than 160 characters, print a warning line to stderr
   (without changing the message or the exit code). Scope: add
   the check to the render command, add tests for a short and a
   long message, document the rule.
4. Add a `notes` field to tracker records, editable with an
   `--note` flag on the add command and shown in the list output.
   Scope: extend the record handling, keep old tracker files
   readable, add tests, document the field in the README.
