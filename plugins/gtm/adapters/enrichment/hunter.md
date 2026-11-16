# enrichment: hunter

## Purpose

Finds and verifies work emails for people at known company domains. Used by `/gtm:campaign-build` after scoring and dedupe, for the people it will add. Hunter does not search companies by ICP.

## Tool

A Hunter MCP connector in the session. Find it with ToolSearch (query `hunter email finder verifier`), and read each schema at run time. Use only its read tools.

Without a connector, Hunter is blocked in this edition: Tessary GTM Pro reads it with an API key (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`, trigger 3). The calls below are the Hunter operations; use the connector's tool for each.

Costs, parameters and status values below were written from Hunter's public documentation and not checked with a live key. Confirm them against the live response and the account call on the first run, and trust the live response when it differs.

| Call | Cost | Use |
|---|---|---|
| `/v2/account` | free | Remaining searches and verifications. |
| `/v2/email-count?domain=` | free | How many addresses Hunter knows for a domain. |
| `/v2/domain-search?domain=` | 1 search credit per call | People and emails at a domain, with position and seniority. |
| `/v2/email-finder?domain=&first_name=&last_name=` | 1 search credit when an email is found | One person's email with a score. |
| `/v2/email-verifier?email=` | 1 verification credit | Deliverability check. |

## Preflight check

ToolSearch for the Hunter connector. Missing: blocked, with the upgrade message as the fix. Present: read the account balance with its account tool, and show the remaining search and verification counts before the first paid call. An auth error is blocked.

## Read procedure

Call Hunter only for people campaign-build will add (after scoring and dedupe), and within the run's credit limit. Ask before passing it.

1. Person with first name, last name and company domain: `email-finder` (domain, first name, last name). Save each result in the scratchpad.
2. Company with no person yet: `email-count` (free) first; when it shows addresses, `domain-search` with `--param seniority=senior,executive` and `--param limit=10`, then keep people whose position matches the ICP buyer titles.
3. Verify each email that is not already `valid` with a high score from the finder: `email-verifier --param email=<address>`.
4. Wait about one second between calls. On a 429, wait and retry once; then stop and report.
5. No paging beyond the first page of `domain-search` unless the target needs it (`--param offset=<n>`).

## Output

Fill the candidate record (`${CLAUDE_PLUGIN_ROOT}/skills/campaign-build/references/candidates.md`):

- `source`: `hunter`. `external_id`: the email address.
- From `domain-search`: `person.first_name`, `last_name`, `title` (position), `linkedin` when given, `email`; `company.name` (organization) and `domain`.
- `email_check` from the verifier, else from the finder's own verification:

| Hunter result | `email_check.result` |
|---|---|
| status `valid` (result `deliverable`), score 90 or more | `valid`, confidence = score |
| status `valid` with a lower score | `valid`, confidence = score (maps to Low Confidence) |
| status `accept_all` | `accept_all` |
| status `unknown` | `unknown` |
| status `invalid` (result `undeliverable`) | `invalid` |
| status `webmail` or `disposable` | `invalid` for a business contact |
| finder found an address but no verification ran | `null` |

- `credits_spent`: one per finder hit, one per domain search, one per verification.

## Cursor

None.

## Blocked signs and fix

- No Hunter connector: the upgrade message (`${CLAUDE_PLUGIN_ROOT}/reference/upgrade.md`), or "Connect a Hunter connector in Claude settings."
- Connector auth error: "Reconnect the Hunter connector in Claude settings."
- 429 after one retry, or zero credits left: report it, stop Hunter calls, keep what was found.

## Write / send capability

None. Read-only.
