# Ideal customer profile

/gtm:setup copies this file to ~/.config/gtm/icp.md and fills it with you. /gtm:campaign-build uses it to search enrichment sources and to score companies (Strong fit, Fit, Not a fit). /gtm:campaign-write uses the pains and signals for its angle. Replace every line in angle brackets.

## Firmographics

- Industry / vertical: <B2B SaaS, developer tools>
- Company size (employees): <10 to 200>
- Stage or revenue: <seed to Series B>
- Geography: <United States, Canada, United Kingdom>
- Business model: <sells software to other businesses>
- Tech or tools they use: <for example a specific CRM, cloud or framework>

## Buyer titles

- Decision maker: <Founder, CEO, CTO>
- Champion: <Head of Sales, VP Engineering>
- Avoid: <interns, recruiters, investors, agencies>

## Pains we solve

- <pain 1, in the buyer's words>
- <pain 2>
- <pain 3>

## Buying signals

Signals that make a company a better fit right now:

- <recently raised a round>
- <hiring for a role that shows the pain (for example "first sales hire")>
- <launched a product or posted about the problem>
- <uses a competitor or a tool we integrate with>

## Exclusions (never contact)

- <current customers and open deals>
- <competitors>
- <companies in regulated sectors we cannot serve>
- <personal email only, no company>

## Negative ICP

Companies that look like a fit but are not. campaign-build marks these Not a fit and records the reason in ICP Notes.

- <too large: enterprise procurement, more than 1000 employees>
- <services firms that resell rather than use>
- <no product yet>

## Fit scoring

- Strong fit: <matches firmographics, has a buyer title, and shows at least one buying signal>
- Fit: <matches firmographics and has a buyer title>
- Not a fit: <matches an exclusion or the negative ICP>
