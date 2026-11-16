# enrichment: hunter

## Purpose

Finds and verifies work emails for people at known company domains. Used by `/gtm:campaign-build` after scoring and dedupe, for the people it will add. Hunter does not search companies by ICP.

## Tool

Preferred: a Hunter MCP connector in the session, when one exists. Find it with ToolSearch (query `hunter email finder verifier`), and read each schema at run time. Use only its read tools.

Otherwise: `lib/readonly_api.py hunter` with the secret `hunter_api_key`. Allowed GET paths: `/v2/account`, `/v2/email-count`, `/v2/domain-search`, `/v2/email-finder`, `/v2/email-verifier`. The client adds the key; never put it in a command line.

Costs, parameters and status values below were written from Hunter's public documentation and not checked with a live key. Confirm them against the live response and the account call on the first run, and trust the live response when it differs.

| Call | Cost | Use |
|---|---|---|
| `/v2/account` | free | Remaining searches and verifications. |
| `/v2/email-count?domain=` | free | How many addresses Hunter knows for a domain. |
| `/v2/domain-search?domain=` | 1 search credit per call | People and emails at a domain, with position and seniority. |
| `/v2/email-finder?domain=&first_name=&last_name=` | 1 search credit when an email is found | One person's email with a score. |
| `/v2/email-verifier?email=` | 1 verification credit | Deliverability check. |

## Preflight check

`python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py hunter check`. Exit 0 = ok, exit 2 = blocked. Not with `runtime` = `cowork` or without Python (`${CLAUDE_PLUGIN_ROOT}/reference/blocked.md`, Cowork). Then read the balance:

```
python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py hunter get /v2/account --out <scratchpad>/hunter-account.json
```

Show the remaining search and verification counts before the first paid call.

## Read procedure

Call Hunter only for people campaign-build will add (after scoring and dedupe), and within the run's credit limit. Ask before passing it.

1. Person with first name, last name and company domain: `email-finder`.
   ```
   python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/readonly_api.py hunter get /v2/email-finder --param domain=<domain> --param first_name=<first> --param last_name=<last> --out <scratchpad>/hf-<n>.json
   ```
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

- `readonly_api.py hunter check` exit 2 with 401: "Save a working key: run `python3 -I -B <plugin root>/lib/config.py set-secret hunter_api_key` in a terminal." (Claude Code only. In Cowork: "Connect a connector for hunter, or run this routine from Claude Code.")
- 429 after one retry, or zero credits left: report it, stop Hunter calls, keep what was found.

## Write / send capability

None. Read-only.
