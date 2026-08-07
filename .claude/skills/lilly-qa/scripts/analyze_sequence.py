#!/usr/bin/env python3
"""
Smartlead Campaign Sequence Analyser

Runs deterministic QA checks on a campaign's sequence JSON (as returned by
`get_campaign_sequences`). Emits structured findings: FAIL / WARN / PASS.

Usage:
    python analyze_sequence.py sequences.json [--playbook navreo|generic]
    python analyze_sequence.py - --playbook generic   # reads JSON from stdin

Output: Markdown report to stdout.
"""

import json
import re
import sys
import argparse
from html import unescape

# ============================================================
# PLAYBOOK PROFILES
# ============================================================

PLAYBOOKS = {
    "generic": {
        "name": "Generic",
        "min_step_delay_days": 3,
        "step1_first_touch_delay_days": 0,
        "min_variants_step1": 1,
        "ps_format": "P.S.",
        "apostrophe_style": "straight",
        "subject_diversity_required": False,
        "internal_domains": [],
    },
    "navreo": {
        "name": "Navreo",
        "min_step_delay_days": 3,
        "step1_first_touch_delay_days": 0,
        "min_variants_step1": 2,
        "ps_format": "P.S.",
        "apostrophe_style": "straight",
        "subject_diversity_required": True,
        "subject_lowercase_warn": True,
        "internal_domains": ["navreo.com", "asteri.com"],
    },
}

# ============================================================
# HELPERS
# ============================================================

def html_to_text(html: str) -> str:
    """Strip HTML to plain text for content reading."""
    h = html.replace("&nbsp;", " ")
    h = re.sub(r"<div[^>]*>", "", h)
    h = re.sub(r"</div>", "\n", h)
    h = re.sub(r"<br\s*/?>", "\n", h)
    h = re.sub(r"<[^>]+>", "", h)
    return unescape(h).strip()


def find_double_braces(text: str) -> list:
    return list(set(re.findall(r"\{\{([^}]+)\}\}", text)))


def find_spintax_outer(text: str) -> list:
    """Find top-level spintax groups, allowing {{var}} nested inside options."""
    cleaned = re.sub(r"\{\{[^}]+\}\}", lambda m: "\x00" * len(m.group(0)), text)
    out, depth, start = [], 0, None
    for i, c in enumerate(cleaned):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                out.append(text[start + 1 : i])
                start = None
    return out


def list_curly_chars(text: str) -> list:
    found = []
    for ch, name in [
        ("\u2018", "curly opening single quote"),
        ("\u2019", "curly apostrophe"),
        ("\u201C", "curly opening double quote"),
        ("\u201D", "curly closing double quote"),
        ("\u2014", "em-dash"),
    ]:
        if ch in text:
            found.append(f"{name} (×{text.count(ch)})")
    return found


def has_mixed_apostrophes(text: str) -> bool:
    return bool(re.search(r"[a-z]'[a-z]", text)) and bool(re.search(r"[a-z]\u2019[a-z]", text))


def render_first_option(text: str) -> str:
    """Render with the first spintax option chosen (for content review)."""
    cleaned = re.sub(r"\{\{[^}]+\}\}", lambda m: "\x01" + m.group(0) + "\x01", text)
    rendered = re.sub(
        r"\{([^{}]*\|[^{}]*)\}",
        lambda m: m.group(1).split("|")[0],
        cleaned,
    )
    return rendered.replace("\x01", "")


# Common SmartLead default variables (lowercase by convention)
DEFAULT_VARS = {"first_name", "last_name", "email", "company_name", "phone_number", "website", "location", "title"}

# Known typo patterns (find -> replace)
TYPO_PATTERNS = [
    (r"\bAlternatively if ", "Alternatively, if ", "missing comma after introductory adverb"),
    (r"which would hold-back", "that would hold back", "wrong relative pronoun + spurious hyphen"),
    (r"\bsales-teams\b", "sales teams", "incorrect hyphenation"),
    (r"P\.S - ", "P.S. ", "P.S. should be period not dash"),
    (r"P\.S\. - ", "P.S. ", "P.S. should not have trailing dash"),
    (r"P\.S -", "P.S.", "P.S. format"),
]

# ============================================================
# CHECKS
# ============================================================


def check_variant_body(label: str, body: str, subject: str | None, playbook: dict) -> tuple[list, list, list]:
    fails, warns, passes = [], [], []

    # Subject checks
    if subject is not None:
        if not subject.strip():
            fails.append(f"{label}: subject empty")
        else:
            passes.append(f"{label}: subject present")
            if list_curly_chars(subject):
                warns.append(f"{label} subject: curly chars present: {list_curly_chars(subject)}")
            if playbook.get("subject_lowercase_warn") and subject and subject[0].islower():
                warns.append(f"{label}: subject starts lowercase: {subject!r}")

            # Spintax in subject
            subj_sp = find_spintax_outer(subject)
            for s in subj_sp:
                if not s.strip():
                    continue
                if "|" not in s:
                    fails.append(f"{label} subject: malformed spintax (no pipe) in '{{{s}}}'")
                else:
                    opts = [o.strip() for o in s.split("|")]
                    if any(not o for o in opts):
                        fails.append(f"{label} subject: empty spintax option")

    # Curly chars in body
    curly = list_curly_chars(body)
    if curly:
        fails.append(f"{label}: curly characters in body: {curly}")
    else:
        passes.append(f"{label}: no curly characters")

    # Mixed apostrophes
    if has_mixed_apostrophes(body):
        fails.append(f"{label}: mixed straight (') and curly (’) apostrophes")

    # &nbsp;
    if "&nbsp;" in body:
        n = body.count("&nbsp;")
        warns.append(f"{label}: {n} &nbsp; character(s) in body")
        if "&nbsp;%signature%" in body:
            warns.append(f"{label}: &nbsp; immediately before %signature% — may misalign signature")
        if re.search(r"\{\{[^}]+\}\}&nbsp;", body):
            warns.append(f"{label}: &nbsp; immediately after a {{variable}} — common artefact, will render as visible space")
    else:
        passes.append(f"{label}: no &nbsp;")

    # Inline style
    if "style=" in body:
        warns.append(f"{label}: inline style= attributes present (verify with plain-text rendering)")

    # %signature%
    if "%signature%" not in body:
        fails.append(f"{label}: missing %signature%")
    else:
        passes.append(f"{label}: %signature% present")

    # [bracket] style placeholders
    brackets = re.findall(r"\[[^\]]+\]", body)
    if brackets:
        fails.append(f"{label}: unsupported [bracket] tokens: {brackets}")

    # Spintax syntax
    sp = find_spintax_outer(body)
    for s in sp:
        if not s.strip():
            continue
        if "|" not in s:
            fails.append(f"{label}: malformed single-curly group (no pipe): '{{{s[:80]}{'...' if len(s)>80 else ''}}}'")
            continue
        opts = [o.strip() for o in s.split("|")]
        if any(not o for o in opts):
            fails.append(f"{label}: empty spintax option in '{{{s[:60]}}}'")

    # Typo patterns
    for pattern, replacement, reason in TYPO_PATTERNS:
        if re.search(pattern, body):
            warns.append(f"{label}: '{pattern.replace(chr(92)+'b', '').replace(chr(92), '')}' → '{replacement}' ({reason})")

    # Custom variable warnings
    vars_used = find_double_braces(body)
    for v in vars_used:
        # Skip SmartLead system variables
        if v.startswith("sl_"):
            continue
        if v.lower() not in DEFAULT_VARS:
            warns.append(f"{label}: uses custom variable {{{{{v}}}}} — verify lead column header is exactly '{v}' (case-sensitive)")

    return fails, warns, passes


def check_step(step: dict, label: str, playbook: dict, expected_subject_empty: bool = True) -> tuple[list, list, list]:
    fails, warns, passes = [], [], []

    delay_obj = step.get("seq_delay_details") or {}
    delay = delay_obj.get("delayInDays", delay_obj.get("delay_in_days", None))

    if expected_subject_empty:
        # Step 2+ must have empty parent subject
        if step.get("subject", "").strip():
            fails.append(f"{label}: subject not empty (follow-ups must have empty subject)")
        else:
            passes.append(f"{label}: subject empty (correct for follow-up)")
        # Delay check
        if delay is not None and delay < playbook["min_step_delay_days"]:
            fails.append(f"{label}: delay = {delay} days, playbook minimum is {playbook['min_step_delay_days']}")
        elif delay is not None:
            passes.append(f"{label}: delay = {delay} days (≥ playbook minimum)")
    else:
        # Step 1 — delay against first-touch convention
        if delay is not None and delay != playbook.get("step1_first_touch_delay_days", 0):
            warns.append(
                f"{label}: first-touch delay = {delay} day(s), convention is "
                f"{playbook.get('step1_first_touch_delay_days', 0)}"
            )
        elif delay is not None:
            passes.append(f"{label}: first-touch delay = {delay} (matches convention)")

    return fails, warns, passes


def check_subject_diversity(variants: list, playbook: dict) -> list:
    warns = []
    subjects = [v.get("subject", "") for v in variants if not v.get("is_deleted")]
    if len(subjects) < 2:
        return warns
    if len(set(subjects)) == 1:
        warns.append(
            f"All {len(subjects)} active Step 1 variants share subject {subjects[0]!r}. "
            "If subject A/B testing was intended, this is not it."
        )
    elif len(set(subjects)) < len(subjects):
        warns.append(f"Some Step 1 variants share subjects: {subjects}")
    return warns


def check_variable_consistency(variants: list) -> list:
    """Flag if some active variants use a variable that others don't."""
    warns = []
    active = [v for v in variants if not v.get("is_deleted")]
    if len(active) < 2:
        return warns

    var_sets = []
    for v in active:
        body = v.get("email_body", "") + " " + v.get("subject", "")
        custom = {var for var in find_double_braces(body) if not var.startswith("sl_") and var.lower() not in DEFAULT_VARS}
        var_sets.append((v.get("variant_label", "?"), custom))

    # Check each custom variable: is it in all active variants?
    all_custom = set()
    for _, s in var_sets:
        all_custom |= s
    for cv in all_custom:
        users = [lab for lab, s in var_sets if cv in s]
        non_users = [lab for lab, s in var_sets if cv not in s]
        if users and non_users:
            warns.append(
                f"Variable {{{{{cv}}}}} used in variant(s) {users} but missing from {non_users}. "
                "Inconsistent personalisation across variants — confirm intentional."
            )
    return warns


def check_deleted_variants(variants: list) -> list:
    warns = []
    deleted = [v for v in variants if v.get("is_deleted")]
    if deleted:
        labels = [v.get("variant_label", "?") for v in deleted]
        warns.append(
            f"{len(deleted)} deleted variant(s) still in database (labels: {labels}). "
            "Verify in UI they're truly removed from the active variant pool."
        )
    return warns


# ============================================================
# MAIN
# ============================================================


def analyse(sequences: list, playbook: dict, campaign_meta: dict | None = None) -> dict:
    """Returns structured findings dict."""
    fails, warns, passes = [], [], []

    if not sequences:
        fails.append("No sequence data provided.")
        return {"fails": fails, "warns": warns, "passes": passes}

    # ---- Step 1 ----
    step1 = sequences[0]
    variants = step1.get("sequence_variants") or []

    # If no variants, treat the parent step's body/subject as the single email
    if not variants:
        warns.append("Step 1 has no variants array — treating parent body as single email")
        if step1.get("subject", "").strip() or step1.get("email_body", "").strip():
            f, w, p = check_variant_body(
                "Step 1",
                step1.get("email_body", ""),
                step1.get("subject", ""),
                playbook,
            )
            fails += f; warns += w; passes += p
        else:
            fails.append("Step 1: parent body and subject both empty, no variants")
    else:
        active = [v for v in variants if not v.get("is_deleted")]
        if len(active) < playbook.get("min_variants_step1", 1):
            warns.append(
                f"Step 1: {len(active)} active variant(s); playbook recommends ≥{playbook['min_variants_step1']}"
            )
        passes.append(f"Step 1: {len(active)} active variants ({len(variants) - len(active)} deleted)")

        for v in variants:
            if v.get("is_deleted"):
                continue
            label = f"Step 1 / Variant {v.get('variant_label', '?')}"
            f, w, p = check_variant_body(label, v.get("email_body", ""), v.get("subject", ""), playbook)
            fails += f; warns += w; passes += p

        # Subject diversity
        warns += check_subject_diversity(variants, playbook)
        # Variable consistency
        warns += check_variable_consistency(variants)
        # Deleted variants
        warns += check_deleted_variants(variants)

    # Step 1 delay (against first-touch convention)
    f, w, p = check_step(step1, "Step 1", playbook, expected_subject_empty=False)
    fails += f; warns += w; passes += p

    # ---- Step 2+ (follow-ups) ----
    for i, step in enumerate(sequences[1:], start=2):
        label = f"Step {i}"
        f, w, p = check_step(step, label, playbook, expected_subject_empty=True)
        fails += f; warns += w; passes += p

        # Body checks
        step_variants = step.get("sequence_variants") or []
        if step_variants:
            for v in step_variants:
                if v.get("is_deleted"):
                    continue
                vlabel = f"{label} / Variant {v.get('variant_label', '?')}"
                f, w, p = check_variant_body(vlabel, v.get("email_body", ""), None, playbook)
                fails += f; warns += w; passes += p
        else:
            f, w, p = check_variant_body(label, step.get("email_body", ""), None, playbook)
            fails += f; warns += w; passes += p

    return {"fails": fails, "warns": warns, "passes": passes, "playbook": playbook["name"]}


def render_report(findings: dict, campaign_meta: dict | None = None) -> str:
    out = []
    if campaign_meta:
        out.append(f"# QA Report — {campaign_meta.get('name', 'Unknown')}")
        out.append("")
        out.append(
            f"**Campaign ID:** {campaign_meta.get('id', '?')} • "
            f"**Status:** {campaign_meta.get('status', '?')} • "
            f"**Playbook:** {findings.get('playbook', '?')}"
        )
        out.append("")
        out.append("---")
        out.append("")

    out.append("## ❌ FAIL — must fix before launch")
    out.append("")
    if findings["fails"]:
        for f in findings["fails"]:
            out.append(f"- {f}")
    else:
        out.append("None — clean run.")
    out.append("")

    out.append("## ⚠️ WARN — review before launch")
    out.append("")
    if findings["warns"]:
        for w in findings["warns"]:
            out.append(f"- {w}")
    else:
        out.append("None.")
    out.append("")

    out.append("## ✅ PASS")
    out.append("")
    if findings["passes"]:
        for p in findings["passes"][:30]:  # truncate if very long
            out.append(f"- {p}")
        if len(findings["passes"]) > 30:
            out.append(f"- ...and {len(findings['passes']) - 30} more")
    else:
        out.append("Nothing passed.")
    out.append("")

    out.append("## 🚫 Cannot verify via API (need UI eyeballs)")
    out.append("")
    out.append("- Mailbox assignment + signatures + per-mailbox sending limits")
    out.append("- Open-rate / click-rate tracking toggles")
    out.append("- Plain text + force plain text settings")
    out.append("- Distribution mode = Randomized")
    out.append("- 50/50 sending pattern")
    out.append("- Schedule (timezone, days, hours, daily limit, start date)")
    out.append("- Suppression / blocklist")
    out.append("- Lead list (status, count, personalisation columns)")
    out.append("- Sub-sequence trigger conditions")
    out.append("")

    out.append("**Note:** This report covers mechanical / deterministic checks only. "
               "A complete QA must also include a human content read for sentence flow, factual claims, "
               "tone consistency, and CTA freshness — none of which are auto-detectable.")

    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Path to sequences JSON file, or '-' for stdin")
    parser.add_argument("--playbook", default="generic", choices=list(PLAYBOOKS.keys()))
    parser.add_argument("--campaign-id")
    parser.add_argument("--campaign-name")
    parser.add_argument("--campaign-status")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of Markdown")
    args = parser.parse_args()

    if args.input == "-":
        data = json.load(sys.stdin)
    else:
        with open(args.input) as f:
            data = json.load(f)

    sequences = data if isinstance(data, list) else data.get("data", data.get("sequences", []))

    playbook = PLAYBOOKS[args.playbook]
    findings = analyse(sequences, playbook)

    meta = {}
    if args.campaign_id: meta["id"] = args.campaign_id
    if args.campaign_name: meta["name"] = args.campaign_name
    if args.campaign_status: meta["status"] = args.campaign_status

    if args.json:
        print(json.dumps(findings, indent=2))
    else:
        print(render_report(findings, meta))


if __name__ == "__main__":
    main()
