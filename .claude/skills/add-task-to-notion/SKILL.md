---
name: add-task-to-notion
description: Create a task in the Notion "Client Tasks" database. Use this skill whenever the user asks to add, create, or log a task, assign work to a teammate, or capture a to-do or build ticket for a client. EVERY task it creates ALWAYS gets a Client and a Due Date assigned (both mandatory, ask if not given); it sets Assigned To when a person is named and defaults Status to "Not started". Trigger phrases: 'add a task', 'create a task', 'add this as a task', 'log a task', 'new task for [client]', 'add a task for [person]', 'add a build task', 'add it to client tasks', 'put this in the Notion tasks', 'task for Asad', 'add a to-do for [client]'. Always writes to the Client Tasks DB only, never the harness/session to-do list and never a different database.
---

# Add Task to Notion

Creates one or more task pages in the Notion **"Client Tasks"** database, the team's shared work tracker. Every task created here MUST have a **Client** and a **Due Date** assigned (this is the standing instruction behind this skill).

## When this runs

- Whenever the user asks to add / create / log a task, assign work to someone, or capture a build ticket or to-do for a client.
- This is for SHARED CLIENT TASKS in Notion. It is NOT the harness session to-do list (`TaskCreate`), and NOT any other database. If the user clearly means a personal/session checklist, that is a different tool, confirm before using this skill.

## Target database

- Parent database page: `2776e75598d98036bc05ff159a6fcd89` ("Client Tasks")
- **Data source (use this as the create parent):** `collection://2776e755-98d9-806a-88af-000b091e215e`
- If the IDs ever change, `notion-search` for "Client Tasks" or `fetch` the database to rediscover the data source from its `<data-source>` tag.

## Mandatory fields (never create a task without BOTH)

1. **Client** (`"Client "` select, note the trailing space in the property name) is REQUIRED. Match the named client to an existing option. If it is a new client, the select auto-creates the option (confirm spelling first). Use `MISC.` only when no client fits. `fetch` the data source for the current option list (it grows as clients are added).
2. **Due Date** (`Due Date` date) is REQUIRED. If the user did not give one, ASK for it before creating (or propose a sensible default and confirm). Convert relative dates ("next Friday", "in 3 days", "EOW", "end of month") to an ISO date using the `currentDate` context.

If either is missing from the request, ask the user. Do NOT create the page until both are set.

## Other fields

| Property | Type | Notes |
|---|---|---|
| `Name` | title | The task title. No em-dashes (this is a handover doc); use hyphens, colons, or parentheses. |
| `Assigned To` | person | A JSON-array string of user IDs, e.g. `["316d872b-594c-8142-9f1c-00027d085e59"]`. Set it when a person is named. Look up IDs via `notion-get-users` (query by name). Known: **Asad Rafique** = `316d872b-594c-8142-9f1c-00027d085e59`. |
| `Status` | status | Default **"Not started"** for a fresh task. Options: Not started, Needs approval, Feedback Provided, Paused, Warm up, Navreo Ball Court, Clients Ball Court, In progress, Done. |
| `Priority` | select | Optional. High / Medium / Low. Set only if the user signals urgency. |

## Task body format (5W + H)

Every task body follows the **5W + H** framework so whoever picks it up has a complete, self-contained brief. **Who** and **When** are already captured in the Notion properties (`Assigned To` and `Due Date`), so the page body covers the remaining four, in this order: **What, Why, Where, How**.

Use these exact `##` section headings every time. Skip a section only when it is genuinely not applicable (e.g. no system or login is involved, so no **Where**).

- **## What** - the concrete deliverable in one or two sentences. State what must be true when the task is done.
- **## Why** - the background and motivation: what happened, why it matters, what the client agreed to. Enough context that the assignee understands the goal, not just the instruction.
- **## Where** - every system, account, login, file, or link the work touches. Put workspace names, the platform (Smartlead / HeyReach / Notion), and document URLs here. If credentials are involved, list them as `Username:` / `Password:` lines at the top of this section.
- **## How** - a light outline of the approach, not a step-by-step script. Sketch the path and flag anything genuinely important (a constraint, a gotcha, the step that is easy to get wrong), then leave the detail to the assignee. The exact steps usually change once they are in the work, so do not spell out every action; trust their judgment and autonomy. A few bullets, or a short numbered list at most, is plenty. Skip this section entirely when the What and Why already make the path obvious.

Keep it scannable: short sentences, `-` bullets, and `1.` numbered lists. No em-dashes (see gotchas). Do not use `<toggle>` or HTML list tags; plain markdown headings and lists render reliably in Notion.

### Example body

```markdown
## What
Rewrite the client's active Smartlead campaign copy. The client has approved the update. Done = a new sequence drafted that doubles down on what made their best-performing campaign land.

## Why
The client ran a campaign that performed well initially. A follow-up then flopped because the copy was lazy and did not build on what worked. It was relaunched but has gone quiet. The client has agreed to let us rewrite it.

## Where
- Smartlead workspace (client account):
  - Username: <client Smartlead email>
  - Password: <provided in the brief>
- Client context doc: <Google Doc URL>

## How
- Work out what made the strong campaign land, then rebuild the current copy around that.
- Key point: do not just relaunch the flopped follow-up as-is. It stopped working because the copy quit building on what landed the first time.
```

## Property-format gotchas (these silently fail if wrong)

- **`"Client "` has a trailing space** in the property name. Include it exactly or the value drops.
- **`Assigned To`** value is a JSON array string of user IDs (not names).
- **Due Date** uses expanded keys: `"date:Due Date:start"` = ISO date (e.g. `2026-06-02`) and `"date:Due Date:is_datetime"` = `0`.
- **Parent must be `data_source_id`** (`2776e755-98d9-806a-88af-000b091e215e`), never `page_id`.
- **No em-dashes** anywhere in the title or body. Hyphens, colons, parentheses are fine.

## Procedure

1. **Parse** the request into: task title, client, due date, assignee (if named), priority (if given), and the body detail. Structure the body with the **5W + H framework** (see above): What, Why, Where, How.
2. **Gate on the mandatory fields:** if Client or Due Date is missing, ask the user. Resolve relative dates against `currentDate`.
3. **Resolve the assignee** if a person is named: `notion-get-users` with a name query returns the user ID. (Asad Rafique is cached above.)
4. **Validate the Client** against the live select options (fetch the data source if unsure). A genuinely new client auto-creates the option, so confirm the spelling first.
5. **Create** the page(s) with `notion-create-pages`, parent `data_source_id = 2776e755-98d9-806a-88af-000b091e215e`. Put the task detail in `content` as a **5W + H** body (What / Why / Where / How, in that order). Default `Status = "Not started"`.
6. **Report** each created task's name + URL.

## Multiple tasks at once

`notion-create-pages` accepts an array of pages under the same parent, so create several tasks in one call. Each one still needs its own Client and Due Date.

## Example `properties` for one task

```json
{
  "Name": "Build Amplifyy campaign - surging-traffic e-commerce brands",
  "Assigned To": "[\"316d872b-594c-8142-9f1c-00027d085e59\"]",
  "Client ": "Amplifyy",
  "Status": "Not started",
  "date:Due Date:start": "2026-06-02",
  "date:Due Date:is_datetime": 0
}
```

## Communication style

Confirm in plain English what you created: the task name(s), client, due date, assignee, and the Notion URL(s). If you had to ask for (or infer) a missing client or due date, say what you set so the user can correct it.

## Related

- `lilly-strategy` and `lilly-bot` often produce build tasks that land in this database.
- `notion-mailbox-sync` is another Notion-writing skill (different database, the Mailboxes tracker).
