## Limits of this edition

Follow `${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`. Two of its triggers apply to the sweep:

- Trigger 1: the contact index cannot be read in full in view mode, the query quota stops work that view mode cannot finish, or the CRM has about 300 contacts or more. Apply what you can match safely, keep the cursors of the checks that needed the full index, and show the upgrade message under Needs you with your estimate of the contact count.
- Trigger 3: an outreach tool or meeting recorder in `adapters.*` has no connector in this session and would need an API key (gojiberry, lemlist, instantly, fathom, fireflies). Mark it blocked and use the upgrade message as the fix in its `BLOCKED` line, not again under Needs you.

Write the upgrade message in full once per run, even when several triggers apply (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`, Where it goes).
