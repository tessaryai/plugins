# Databases: create or map

Setup step 4. All work here uses the Notion MCP tools (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`). Load `notion-search`, `notion-fetch`, `notion-create-database`, `notion-update-data-source`, `notion-create-pages` with one ToolSearch call and read each schema before the first call. The schema of `notion-create-database` and `notion-update-data-source` defines how properties, select options and relations are written (often a DDL-like or JSON property spec); follow it exactly.

Ids to record: the parent page id, one data source id per database, and the Funnel page id. A database can hold several data sources; gtm uses the data source id (shown by `notion-fetch` on the database, often as `collection://<id>`). Never store a database id or a view id in `notion.data_sources`.

Also record one default view URL per database in `notion.views.<db>` (contacts, companies, pipeline, campaigns, meetings). Skills read every row through this view in the MCP view mode, because rows and SQL mode share a small workspace quota (`${CLAUDE_PLUGIN_ROOT}/reference/notion-access.md`, Query rows). To find it, `notion-fetch` the database (not the data source): the result lists the database's views as `view://<id>` URLs. Pick the default table view, check that it has no filter (a filtered view hides rows from every skill), and store that `view://<view id>` URL as it is: the query tool accepts it as `view_url`. Skills also accept the form `https://www.notion.so/<database id without dashes>?v=<view id without dashes>` (for example a view link the user pastes), but setup records the `view://` form. Set it with `python3 -I -B ${CLAUDE_PLUGIN_ROOT}/lib/config.py set notion.views.<db> '<url>'`. If the only view has a filter, ask the user to add an unfiltered table view (or agree that you create one with `notion-create-view`), then record that one.

## A. Create new databases

1. Parent page. Ask the user for the page title or link. Find it with `notion-search`, show the title and its location, and get a yes. Do not create the databases at the workspace root.
2. Check for leftovers. `notion-fetch` the parent page. If it already holds databases named Contacts, Companies, Pipeline, Campaigns or Meetings (for example from an earlier setup that stopped), ask whether to map those (section B) instead of creating duplicates.
3. Read `${CLAUDE_PLUGIN_ROOT}/templates/schema.json`. For each database in `create_order` (companies, campaigns, pipeline, meetings, contacts):
   - Create it under the parent with its `title` and every property that is not a relation. Title property name = the `name` of the `title` property (for example `Campaign Name` for campaigns).
   - Select properties get their options from `options`, in order. Every choice field is a `select`, never a Notion `status` property.
   - Record the data source id (`collection://<id>`) from the create result. `notion-fetch` the database only when the result does not show it.
   - Record the default view URL in `notion.views.<db>` (see above). A new database has one unfiltered table view; fetch the database to read its `view://` URL and record it in that form.
   - If the tool takes a DDL-like spec, map types as: title → TITLE, rich_text → RICH_TEXT, number → NUMBER, select → SELECT with options, date → DATE, checkbox → CHECKBOX, email → EMAIL, url → URL, phone_number → PHONE_NUMBER. Option colours are optional. A dual relation looks like `ADD COLUMN "Company" RELATION('<target data source id>', DUAL 'Contacts')`. Always follow the live tool schema if it differs.
4. Relations. For each entry in `relation_pairs`, add one dual (two-way) relation from the `from` side with `notion-update-data-source`: property `name` from the `from` property, target = the `to` database's data source id, dual property name = the `to` property's `name`. Create each pair once. Do not add it again from the other side.
5. Verify. `notion-fetch` each data source. Check that `notion.views` holds a view URL for all five databases. Check that every property in schema.json exists with the right type (a `rich_text` property reads back as type `text`; that is a match), that the select options are present, and that each relation shows on both sides with the expected names. Fix gaps with `notion-update-data-source`. Report anything you could not fix under Needs you.
6. Funnel page. Create a plain page under the parent with `notion-create-pages`: title `Funnel` (from `pages[0].title`), content `pages[0].initial_content`. If the tool asks you to read a Markdown spec resource before you write content, read it first. Record its page id.
7. Maps. With created databases, `field_map`, `status_map` and `option_map` are the defaults from schema.json (identity). Set them explicitly anyway in step 5 so a later schema change in the plugin cannot change the user's map. `select_payload` is `{}`.

If a create call fails half-way, do not delete what was created. Fetch the parent, record what exists, and continue from the first missing database or relation. Never pass a flag that deletes content.

## B. Map existing databases

1. Find them. Ask for the page that holds the CRM, or search by likely names (`Contacts`, `People`, `Leads`, `Companies`, `Accounts`, `Deals`, `Pipeline`, `Opportunities`, `Campaigns`, `Meetings`). Show each candidate (title, parent, row count if shown) and let the user pick one per logical database. A logical database the user does not have can be created as in section A, under the same parent, with their consent.
2. Fetch each picked data source with `notion-fetch` (or `notion_rest.py schema <id>` when a token is saved). Note each property's name, type and options. Fetch each picked database too and record its default unfiltered view URL in `notion.views.<db>` (see above).
3. Propose `field_map`. For each logical field in `${CLAUDE_PLUGIN_ROOT}/reference/config.md`, pick the user's property by meaning and type, not by name alone:
   - Types must fit: email ↔ email, url ↔ url, date ↔ date, checkbox ↔ checkbox, number ↔ number, select ↔ select or status, relation ↔ relation to the right database, text ↔ rich_text. A text field holding emails is a fit only for reading; say so.
   - Leave a logical field unmapped when nothing fits, and mark it.
4. Propose `status_map` for the contact Status property. Show the user's options next to the eight logical statuses (New, Contacted, Responded, Discovery, Lead, Archived, Do Not Contact, Disqualified). Each logical status needs its own option; two logical statuses may not share one (`config.py check` rejects that). If the user's ladder has extra options (for example `Nurture`), they stay unmapped; tell the user skills will treat a contact in an unmapped option as unknown and will not change it.
5. Propose `option_map` for the other selects (email_status, lead_source, designation, icp, vertical, stage, likelihood, campaign status and type, meeting source) the same way.
6. Status properties. If a mapped choice field is a real Notion `status` property, not a select, record it in `select_payload` with a flat key, for example `{"contacts.status": "status"}`.
7. Show one table per database: logical field, the user's property, type, and `missing` where nothing fits. Get a yes or corrections.
8. Missing pieces. List the required gaps:
   - Contacts: `status`, `do_not_contact`, `first_contacted`, `email` or `linkedin`, `campaign` relation, and the Status options needed for the ladder.
   - Campaigns: `status` with an Active option, and the `contacts` relation (the dual of contacts.campaign).
   Every logical status needs its own Status option, because `config.py check` fails without all eight distinct values. If the user declines to add a missing Status option, setup cannot finish the map. Offer to point that logical status at an existing unused option the user picks, or stop the mapping and leave config unwritten.
   Offer to add each missing property or option with `notion-update-data-source`. Add only what the user agrees to. Never rename, retype or delete an existing property or option. For a field the user declines, keep the default name in `field_map` so `check` passes, and tell the user that skills will skip writes to it and report it once under Needs you.
9. Funnel page. Ask whether to create the Funnel page under the CRM page or use an existing empty page. Warn that `/gtm:funnel` replaces the whole page each run, so it must hold nothing else.

## Never

- Never delete or move a database, page or property.
- Never change an existing option's name or colour.
- Never write rows during setup. Imports are `/gtm:import`.
