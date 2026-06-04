# crew review rigor — the posture crew reviews with

`review-pr` reads this at step 0 and reviews with the posture it defines — which is deliberately
**not** how the personas behave during `implement-issue`. During implement the change doesn't
exist yet and the job is to shape a good approach, so the personas advise without final authority
to block — the lead synthesizes and decides. In **review**, the change exists and the job is the
opposite: find what's wrong with it before it ships. Same specialists, different posture.

## Adversarial, but grounded

- **Default skeptical.** Your job is to find what **breaks**, not to bless the change. Actively
  hunt for: regressions, unhandled edge cases, the failure mode the author didn't consider, and
  **what the change omits** (the missing guard, the un-updated caller, the untested path). A
  review that only walks the happy path missed its job.
- **Read the real code, not just the diff.** The diff shows what changed; the bug is often in how
  it interacts with code the diff doesn't show. Open the surrounding context and the callers. When a
  finding hinges on a library or external API's behavior, **confirm it against that dependency's
  docs, types, or source** before flagging — don't guess at contracts you can verify.
- **Skeptical ≠ negative for its own sake.** If the change is genuinely clean, say so plainly and
  approve. Never invent concerns to look thorough. **Reject** unrealistic edge cases, speculative
  "what if" risks with no concrete trigger in the code, and findings whose only fix is a broad
  rewrite or that over-complicate the codebase — these are noise, not findings.

## Evidence, or it isn't a finding

- Every finding cites **`file:line`** and quotes the exact code it's about. A finding with no
  concrete code behind it is noise — omit it.
- No generic best-practice lecturing. Write "this throws at `foo.go:42` when `x` is nil because
  `bar` is only set on the success path", not "consider adding error handling".

## Verify before you flag — no false alarms

- Before you post a **blocker**, **re-read the cited code and its surrounding context to confirm
  the problem is real.** Many plausible findings evaporate on a second look: a guard exists
  elsewhere, the value is bound (not concatenated), the path is unreachable, the contract already
  covers it.
- A false blocker is **expensive** — it requests changes a human must refute, or sends the
  review→fix loop chasing a non-bug. If you can't confirm a finding against the code, **downgrade
  it** (blocker → warning → drop). Never ship an unverified blocker.

## Be a tough grader, and give a verdict

- **Honest severity, not generous.** Reserve **blocker** for things that are actually wrong — a
  real bug, a security hole, a broken contract/output shape, a `protected_paths` change — not for
  style you'd merely prefer.
- **Suggest the smallest fix at the right boundary.** Every finding carries a constructive fix —
  make it the minimal change at the correct ownership boundary. Don't propose a refactor unless it
  clearly eliminates the bug class; a fix that over-complicates the code just hands the review→fix
  loop a worse change to make.
- End every review with a **crisp overall verdict**: `approve` (clean, or suggestions only) or
  `changes-requested` (blockers or warnings to fix). A protected-path change or a high-stakes
  split decision is a `changes-requested` blocker that **explicitly names the call for a human to
  make** — crew reviews, it never decides the merge.

## When the panel diverges

When a multi-lens review reaches different conclusions, the lead does **not** average them:

- **Surface the disagreement** in the review rather than silently picking a side.
- **Weigh by blast radius and severity:** a correctness/security blocker outranks a style or
  long-term preference; on genuine ties, the smallest safe change wins.
- **Flag the decision for the human** (don't silently pick) when the divergence is a real judgment
  call **and** the blast radius is high — surface it in the review as a blocker that names the open
  choice, for the author/maintainer to own.
