---
name: publish-skill
description: "Publish a newly-created or modified Claude skill to Notion (under the Claude Skills parent page) and push the change to the navreo-claude-skills GitHub repo. Auto-fires via a PostToolUse hook whenever any SKILL.md inside ~/.claude/skills/ is written or edited — but can also be invoked manually. The skill handles both new-skill registration (creates a Notion page following the lilly-bot template) and skill updates (skips Notion creation if a page already exists, always commits + pushes). Trigger phrases: 'publish the skill', 'register the new skill', 'push the skill to Notion and GitHub', 'ship the skill', 'commit and push the skills repo'. Also fires automatically via hook on any SKILL.md write."
---

# Publish Skill

## Purpose

Two-step workflow that runs every time a SKILL.md is created or modified inside `~/.claude/skills/`:

1. **Notion** — if the skill is new (no existing Notion page under the "Claude Skills" parent), create a page following the lilly-bot template. If a page already exists, **update it in place** to reflect the current SKILL.md (modified skills refresh Notion too, set 2026-05-22).
2. **GitHub** — `git add` the changed skill directory, commit with an auto-generated message, push to `bjionhenry94/navreo-claude-skills`.

The skill is invoked:
- **Automatically** via a PostToolUse hook (registered in `~/.claude/settings.json`) that fires on every `Write`/`Edit` to a file matching `**/.claude/skills/*/SKILL.md`. The hook prints a system reminder; this skill picks up the work.
- **Manually** when the user says "publish the skill", "ship it", or similar.

---

## When to Use

Trigger whenever:
- A new skill directory + SKILL.md was just created in `~/.claude/skills/`
- An existing skill's SKILL.md was edited
- The user explicitly asks to publish / register / ship a skill
- The hook system reminder fires after a SKILL.md write

Skip when:
- The user explicitly says "don't push yet" / "skip Notion this time"
- Only non-SKILL.md files changed (e.g. a script or reference file inside the skill — those still get committed by the git step but don't trigger a Notion page)

---

## Inputs

| Input | Required | Notes |
|---|---|---|
| Skill name (e.g. `lilly-heyreach-upload`) | Optional | If omitted, auto-detect from `git status` — process every skill with new or modified SKILL.md |
| Skip Notion? | Optional | Default no. Set yes if the user explicitly opts out for this run |
| Custom commit message | Optional | Default is auto-generated from the changed/added skills |

---

## Workflow

### Step 1 — Identify the skill(s) to publish

```bash
cd ~/.claude/skills
# New skills (untracked SKILL.md)
git ls-files --others --exclude-standard | grep -E '^[^/]+/SKILL\.md$' | sed -E 's|/SKILL\.md$||'
# Modified skills
git diff --name-only HEAD -- '*/SKILL.md' | sed -E 's|/SKILL\.md$||'
```

Combine both. Deduplicate. For each skill name:

- **New** if the SKILL.md is untracked (`git ls-files --others`)
- **Modified** if it's tracked but has uncommitted changes

### Step 2 — For each NEW skill: create the Notion page

1. **Check first**: search Notion for an existing page with this skill name under the "Claude Skills" parent (page id `3556e755-98d9-8018-a5c3-d37d36879fa5`). Use `mcp__86465736-…-notion-search` with the skill name as the query. If a page exists with the exact title match, **skip** — log "Notion page already exists; skipping create."
2. **Read the SKILL.md frontmatter** to get `name` and `description`.
3. **Read the SKILL.md body** to extract the gist (purpose, when to use, workflow steps, key gotchas).
4. **Generate Notion content** following the **lilly-bot template** (the canonical structure):

```markdown
# What it does
<one-paragraph summary from the SKILL.md Purpose section + the "does/doesn't" clarifications>

---
# How to initiate it
Type `/<skill-name>` with <typical input>.

## Optimal input template
```
/<skill-name>

<key inputs>
```

## Minimum viable input
```
/<skill-name>

<simplest invocation>
```

---
# How it works
<table header-row="true">
<tr><td>Step</td><td>Purpose</td></tr>
<tr><td>1</td><td><step 1 summary from SKILL.md Workflow></td></tr>
…
</table>

**Critical guardrails (non-negotiable):**
- <pull from SKILL.md Guardrails section>

---
# Tools used
## APIs
- <list APIs from SKILL.md>
## Built-in Claude tools
- <Read, Bash, Write, etc.>
## Skills it delegates to
- <if any>

---
# When to use vs. when not to use
<table header-row="true">
<tr><td>Use it when</td><td>Skip it for</td></tr>
…
</table>

---
# Source of truth
The canonical skill file lives at:
`~/.claude/skills/<skill-name>/SKILL.md`
This is one of the skills in the private **`navreo-claude-skills` GitHub repo**: [github.com/bjionhenry94/navreo-claude-skills](http://github.com/bjionhenry94/navreo-claude-skills)
**To change a skill**: edit the `SKILL.md` file → ask Lilly to commit + tag a new version + push to GitHub. Teammates run `git pull` to get it.
This Notion page is a quick-reference summary; versioning lives in Git.

---
# Version history
Versioning lives in Git. Each release is a tag in the `navreo-claude-skills` repo.
- **All versions**: [github.com/bjionhenry94/navreo-claude-skills/tags](http://github.com/bjionhenry94/navreo-claude-skills/tags)
- **Current**: `v1.0` (<today's date>) — initial release
- **To roll back to any version**: `cd ~/.claude/skills && git checkout v1.0`
- **To see what changed between versions**: `git diff v1.0 v1.1`
```

5. **Pick an icon** — use the skill's domain (🤖 for Lilly bots, 🔗 for upload/integration, 🔍 for search, 📊 for analytics, etc.).
6. **Create the page** via `mcp__86465736-…-notion-create-pages` with parent `{"type": "page_id", "page_id": "3556e75598d98018a5c3d37d36879fa5"}`.
7. Record the page URL — include in the user-facing summary at the end.

### Step 3 — For each MODIFIED skill: refresh its Notion page

Modified skills DO get their Notion page updated (set 2026-05-22: a stale Notion page is worse than none). Workflow:
1. Find the existing page: `notion-search` for the skill name under the "Claude Skills" parent (`3556e75598d98018a5c3d37d36879fa5`).
2. `notion-fetch` the page to load its current content.
3. Diff against the current SKILL.md and apply targeted `notion-update-page` → `update_content` edits (search-and-replace per changed section). Use `replace_content` only if the page has drifted far from the template. Keep the lilly-bot template structure.
4. Bump the Version history block: add a dated line summarising what changed.

Do NOT create a second page, always update the existing one. If no page exists yet (skill was never published to Notion), fall back to the Step 2 create flow.

### Step 4 — git add, commit, push

```bash
cd ~/.claude/skills
# Stage every changed/new skill directory (not the entire tree — only what we publish)
for skill in <list of names>; do
  git add "$skill/"
done

# Auto-generated commit message
git commit -m "<auto message>"
git push origin main
```

**Commit message pattern:**
- 1 new skill: `Add <skill-name>: <one-line description from frontmatter>`
- 1 modified skill: `Update <skill-name>: <brief summary inferred from diff>`
- Multiple: `Add/update N skills: <skill1>, <skill2>, …` with a body listing each

**Use heredoc for the message** to keep multi-line bodies clean:

```bash
git commit -m "$(cat <<'EOF'
Add lilly-heyreach-upload: HeyReach LinkedIn campaign skill

Captures the HeyReach REST API workflow learned during the Boomerang-followers
campaign push (4,370 leads, 4 lists). LinkedIn equivalent of lilly-bot.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Step 5 — Report

Print a short summary:

```
Published:
- lilly-heyreach-upload (NEW) → Notion: https://notion.so/… 
- lilly-email-verification (modified) → Notion skipped (existing page)

Commit: <sha> "Add lilly-heyreach-upload: …"
Pushed to origin/main.
```

---

## Guardrails

1. **Never auto-push without the user's explicit pre-authorization for this workflow.** The user explicitly set this up as an "always execute" workflow on 2026-05-17 — that authorization stands. But if the user says "don't push" during a run, stop immediately.
2. **For a modified skill, update the existing Notion page in place** (via `notion-update-page`) to keep it current. Do not skip it, and do not create a duplicate. The only branch is create-vs-update: new skill → `create-pages`, existing page → `update-page`. Preserve the lilly-bot template structure and any child elements; prefer targeted `update_content` edits over a full `replace_content` where practical.
3. **Never push WIP commits.** Run `git status` first; if there are uncommitted changes OUTSIDE the skill directories being published (e.g. random edits to settings.json or other skills the user didn't ask to ship), surface them and ask before committing.
4. **Never push to `main` if branch is detached or behind upstream.** Pull first via `git pull --ff-only` if behind.
5. **Skip hooks (`--no-verify`) is FORBIDDEN.** Pre-commit hooks (if any) must pass.
6. **Don't fire the hook reminder for `Write`/`Edit` on files OTHER than SKILL.md.** The hook script filters by path; if it ever fires for the wrong path, fix the matcher, don't disable the hook.
7. **Notion content follows the lilly-bot template strictly.** Don't invent new sections; if a section doesn't apply, omit it cleanly (e.g. a skill with no API dependencies just has `## APIs: None` or skips that subsection).
8. **The skill name in Notion title** must exactly match the directory name AND the `name` field in SKILL.md frontmatter. No spaces, no version suffixes.
9. **GitHub push goes to `main` by default.** No PR flow — this is a personal skills repo for fast iteration.

---

## Common pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| Hook fires but skill doesn't auto-invoke | The reminder prints but Claude doesn't run `/publish-skill` | Claude needs to see the reminder — verify the hook is PostToolUse, not PreToolUse; verify stdout from hook script reaches Claude's context |
| Notion page created twice | Two pages with the same title | Always search first via `notion-search` before `create-pages`. If results contain an exact-title match under the right parent, skip create. |
| Commit message references a skill that wasn't actually changed | Auto-detection picked up an unrelated file | Filter `git status` strictly to `*/SKILL.md` paths; ignore other changes |
| Push fails on auth | `git push` returns 401/403 | Ensure `gh auth status` is OK; `gh auth login --git-protocol https` if not |
| `gh` not in PATH | `command not found: gh` | gh is at `~/.local/bin/gh` per memory; prepend that path or use full path |
| Conflict on push | `! [rejected] main -> main (fetch first)` | `git pull --rebase origin main` before retrying push |

---

## Auto-trigger hook

A PostToolUse hook in `~/.claude/settings.json` fires this skill whenever a SKILL.md is written or edited:

```json
"PostToolUse": [
  {
    "matcher": "Write|Edit",
    "hooks": [
      {
        "type": "command",
        "command": "/Users/bjionhenry/.claude/hooks/publish-skill-reminder.sh"
      }
    ]
  }
]
```

The hook script at `~/.claude/hooks/publish-skill-reminder.sh`:
- Reads the tool input JSON from stdin
- Checks if the tool was Write/Edit on a path matching `*/.claude/skills/*/SKILL.md`
- If yes, prints a system reminder asking Claude to invoke `/publish-skill`
- Otherwise exits silently

**To temporarily disable**: comment out the PostToolUse entry in settings.json, or rename the hook script. Re-enable by uncommenting / restoring.

---

## Quick reference

```bash
# Manual invocation
/publish-skill                    # auto-detect all changed/new skills
/publish-skill lilly-foo          # publish just one skill

# Under the hood
cd ~/.claude/skills
git ls-files --others --exclude-standard | grep -E '/SKILL\.md$'   # new skills
git diff --name-only HEAD -- '*/SKILL.md'                          # modified skills
git add <skill>/ && git commit -m "..." && git push origin main
```

---

## Source of truth

The canonical skill file lives at:
`~/.claude/skills/publish-skill/SKILL.md`

This is one of the skills in the private **`navreo-claude-skills` GitHub repo**: [github.com/bjionhenry94/navreo-claude-skills](http://github.com/bjionhenry94/navreo-claude-skills)
