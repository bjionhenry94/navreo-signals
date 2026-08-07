---
name: lilly-tag-accounts
description: "Create, assign, remove, and read TAGS on Smartlead email accounts (mailboxes / sending inboxes), including bulk tagging a whole sender pool by provider type, domain, or smtp host. Use this skill whenever the user wants to tag, label, segment, group, or organise email accounts / mailboxes / inboxes / senders in Smartlead — e.g. 'tag the Outlook ones X', 'label all the Maildoso mailboxes', 'tag every amplifyy-domain sender', 'segment inboxes by provider', 'add a tag to these mailboxes', 'untag', 'remove a tag from accounts', or 'what tags does this mailbox have'. Trigger even if they don't say the word 'tag' but clearly want to label or group sending accounts. NOTE: this is for EMAIL ACCOUNTS (sender mailboxes), not leads — lead/contact tagging is different."
---

# Lilly Tags Email Accounts in SmartLead

## Purpose

Manage tags on Smartlead **email accounts** (the sending mailboxes), one-off or in bulk. The common job is labelling a large sender pool by provider or client, e.g. tag every Outlook inbox `Amplifyy - Hypertide` and every Maildoso inbox `Amplifyy - Maildoso`, so the inbox list can be filtered/segmented in the UI.

This is sender-infrastructure tagging. It is NOT lead tagging and NOT campaign tagging.

---

## Critical API Knowledge

Tagging email accounts is **undocumented in the obvious place** and the public docs are wrong about it. The endpoints below are verified working (2026-05). Base URL `https://server.smartlead.ai/api/v1`, auth via `?api_key=`.

### The endpoints (tags are a first-class resource, NOT under /email-accounts/tag)

Anything `POST /email-accounts/<non-numeric>` collides with the update route `POST /email-accounts/:account_id` and 400s (`"account_id" must be a number`). Old skill kits that POST to `/email-accounts/tag` are **dead**. The real flow is three separate resources:

| Op | Method + path | Body |
|---|---|---|
| **Create tag** | `POST /tags` | `{"name": "...", "color": "#RRGGBB"}` → `201 {data:{id,...}}` |
| **Assign** | `POST /email-accounts/tag-mapping` | `{"email_account_ids":[≤25], "tag_ids":[≥1]}` |
| **Unassign** | `DELETE /email-accounts/tag-mapping` | same body as assign |
| **Read tags** | `POST /email-accounts/tag-list` | `{"email_ids":["a@x.com", ...]}` → `{data:[{email_account_id, email_id, tags:[{tag_id, tag_name}]}]}` |

### Behaviours that matter

- **Assign is additive + idempotent.** Adding a tag preserves a mailbox's existing tags (response `summary:{added,skipped,failed}`). There is **no read-modify-write needed** — do NOT read the current list and re-post it (that was only required by the old replace-style endpoint). Re-running is safe (already-mapped → `skipped`).
- **Unassign is granular** — removing one tag leaves the others (`summary:{deleted,...}`).
- **Tags are objects, created once and reused by id** across many accounts. Don't pass `{name,color}` inline to the mapping call.
- **`POST /tags` always creates** — there is no get-tag-by-name and no list-all-tags endpoint, so re-creating the same name makes a duplicate. To reuse, pass the existing `tag_id` (the script reuses automatically if the name is already on a sampled account).
- **Tags do NOT appear** on `GET /email-accounts` or `GET /email-accounts/{id}`. The only way to read a mailbox's tags is `POST /email-accounts/tag-list`.
- **No delete-tag-definition endpoint** (`DELETE /tags/{id}`, `DELETE /tags`, `POST /tags/delete` all 404). Orphaned tag objects can only be deleted in the Smartlead UI. So avoid creating throwaway tags.
- **Provider/type:** the account `.type` field is the clean classifier — `OUTLOOK` (Hypertide-provisioned Microsoft inboxes) vs `SMTP` (Maildoso uses `smtp_host = smtp.maildoso.com`). Google would be `GMAIL`.

### Plumbing gotchas

- **Auth:** `SMARTLEAD_API_KEY` lives in `~/.navreo-keys.env`. It is NOT auto-exported to non-interactive shells — `grep` it out; do NOT `set -a; source` the file (that clobbers `PATH`). The bundled script handles this.
- **Use curl, not python-urllib.** Smartlead's Cloudflare blocks bare python user-agents. The script shells out to curl.
- **Rate limit: 200 requests / 1 min, SHARED with the account's live sending.** Bursty calls hit 429 easily. Always retry on 429 (the script backs off 12s). A full account pull is ~85 GET calls — expect occasional 429s.
- **zsh footgun** if you ever hand-roll a loop: never use `path` as a loop variable (it's tied to `$PATH`).

---

## The bundled script — `scripts/tag_accounts.py`

Use this for everything. It pulls all accounts, applies selection filters, and is **dry-run by default** — it prints the matched set + breakdown and writes nothing until you add `--apply`. This enforces the confirm-before-fire rule below.

```bash
cd <skill-dir>/scripts

# DRY RUN — see the matched set first (no writes)
python3 tag_accounts.py --type OUTLOOK --domain-contains amplifyy

# create a tag + assign it
python3 tag_accounts.py --type OUTLOOK --domain-contains amplifyy \
    --tag "Amplifyy - Hypertide" --color "#2563eb" --apply

# assign an EXISTING tag by id (no duplicate definition)
python3 tag_accounts.py --type SMTP --domain-contains amplifyy --tag-id 405504 --apply

# real Amplifyy-Maildoso scope: every 'amplify' domain EXCEPT navreo's own
# (--domain-contains amplify catches amplifyy*, amplifyseller, amplifymarketplace, navreoamplify)
python3 tag_accounts.py --type SMTP --domain-contains amplify \
    --exclude-domain navreoamplify.info \
    --tag "Amplifyy - Maildoso" --color "#16a34a" --apply

# remove a tag from a selection
python3 tag_accounts.py --domain-in amplifyseller.info --tag-id 405504 --action remove --apply

# read current tags for specific mailboxes (no full pull)
python3 tag_accounts.py --read --emails kevindormer@amplifyysales.info
```

Selection flags (AND-ed): `--type`, `--domain-contains`, `--domain-in`, `--exclude-domain`, `--smtp-host`, `--from-name-contains`, `--ids`, `--ids-from-csv`. Action: `--tag` / `--tag-id`, `--color`, `--action assign|remove`, `--read`, `--apply`. Batches of 25, 429 retry, verifies a sample after applying.

**Filters are AND-ed**, not OR-ed. So `--domain-contains amplifyy --domain-in amplifyseller.info` matches nothing (a domain can't satisfy both). To express an OR across domains, widen `--domain-contains` to a shorter shared substring and drop the unwanted ones with `--exclude-domain` (e.g. `--domain-contains amplify --exclude-domain navreoamplify.info` to get every amplify*/amplifyy* domain except Navreo's).

---

## Workflow

1. **Clarify the scope as literal filters.** Turn the request into concrete selection flags (type? domain substring? exact domains? exclusions?). Never auto-infer — sender pools are multi-client, so mis-scoping mislabels another client's infra.
2. **Dry run first.** Run the script without `--apply`. Read out the matched count, the by-type breakdown, distinct domains, and a 10-row sample.
3. **Surface edge cases and confirm.** Call out anything ambiguous in plain English — e.g. one-`y` `amplify` domains vs two-`y` `amplifyy`, or a `navreo*`-prefixed domain that may belong to Navreo rather than the client. Get an explicit go before writing. (This is a hard rule for bulk writes on a client account.)
4. **Apply.** Re-run with `--apply`. For a re-run or a second tag onto an existing definition, pass `--tag-id` to avoid duplicate tag objects.
5. **Verify.** The script reads back a sample; confirm the tag landed and that pre-existing tags survived (assign is additive, so they should).

### Communication style
Talk in plain English to the user: "1,039 Outlook mailboxes on amplifyy domains" — not "matched .type==OUTLOOK". Report counts, the exact inclusion/exclusion you used, and `added/skipped/failed`. Avoid jargon like substring, array, crosstab.

---

## Scope & safety

- **Add, never replace — this is the default and it is NOT optional.** Assigning is purely additive: it never removes a mailbox's existing tags (the API maps individual tags, it does not overwrite the list), so you never read-then-rewrite. **Never wipe or replace a tag as a side effect of adding one.** If a request only *sounds* like replacement — "change the tag to X", "make it just X", "swap / retag as X", "move them to X", "they should only have X" — do NOT silently remove anything. First tell the user **exactly which tag(s) would be removed**, get explicit confirmation, and only THEN `--action remove` those plus assign the new one. Removal is the single destructive operation here, so it is always explicit and confirmed. The script enforces this: `--action assign` (add) is the default; removal requires an explicit `--action remove`.
- **Confirm inclusions/exclusions before firing** any bulk apply. The dry-run default exists for this; don't bypass it.
- **Don't create throwaway/test tags** on the live workspace — there's no API to delete a tag definition, so they linger until removed in the UI. Test on one real mailbox with the real tag instead.
- Tagging email accounts has **no effect on sending, warmup, or campaigns** — it's purely a label for filtering the inbox list. Reversible via `--action remove`.

## Related
`lilly-bot` (campaign building), `email-deliverability-audit` (per-inbox health, also reads the account list), `notion-mailbox-sync` (per-domain mailbox health → Notion). Mailbox-tag state is not visible on the standard account endpoints, so this skill's `--read` is the source of truth for what tags a mailbox carries.
