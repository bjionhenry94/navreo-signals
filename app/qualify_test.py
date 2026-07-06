#!/usr/bin/env python3
"""Fixture test for qualify_engager (engagement-signal Step 3 done-rule).

6 fixtures: 2 clear-fit, 2 clear-miss (title / geo), 1 off-topic post,
1 borderline. Passes when both clear-fits come back QUALIFIED, all three
clear-misses come back OFF_BRIEF, and the geo miss shows method=string-gate
(zero OpenAI calls).

Run:  python3 app/qualify_test.py
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import QUALIFY_CACHE, qualify_engager  # noqa: E402

CFG = {
    "engagement": {
        "include_topics": ["Tooling", "AI-for-sales", "GTM strategy", "GTM tutorials and giveaways"],
        "wildcard": "posts comparing outbound tools",
        "avoid_topics": ["Anniversaries", "Personal stories", "Stories about struggles and triumphs",
                         "Life lessons", "Sad or unfortunate posts or news"],
        "engager_titles": ["Founder", "CEO", "Head of Sales", "VP Sales", "CRO", "Head of GTM",
                           "Head of Growth", "Head of Marketing"],
        "avoid_rules": "no recruiters, no direct lead-gen agencies",
    },
    "countries": ["United States", "United Kingdom", "Canada", "Australia", "Ireland", "New Zealand",
                  "Germany", "Netherlands", "Switzerland", "Sweden", "Norway", "Denmark", "Finland", "Singapore"],
    "headcount": ["11-20", "21-50", "51-100", "101-200"],
}

GTM_POST = ("Most cold email campaigns die in the first sentence. Here's the GTM playbook we used "
            "to book 40 calls last month with AI-assisted personalisation and a 3-step sequence...")

FIXTURES = [
    ("clear-fit-1", "QUALIFIED", {
        "post_author_name": "Competitor Founder", "post_text": GTM_POST,
        "engagement_type": "comment", "comment_text": "Great breakdown, we struggle with step 2",
        "engager_job_title": "VP Sales", "engager_headline": "VP Sales at Acme SaaS",
        "engager_company_name": "Acme SaaS", "engager_company_industry": "Software Development",
        "engager_company_description": "B2B workflow software for mid-market ops teams",
        "engager_company_headcount": "51-100", "engager_country": "United States",
        "engager_linkedin_url": "https://www.linkedin.com/in/fixture-fit-1", "post_url": "p1"}),
    ("clear-fit-2", "QUALIFIED", {
        "post_author_name": "Competitor Founder",
        "post_text": "Free giveaway: our GTM tutorial - the exact outbound tooling stack we run, step by step.",
        "engagement_type": "like", "comment_text": None,
        "engager_job_title": "Founder", "engager_headline": "Founder @ Northbeam - custom software development for fintech",
        "engager_company_name": "Northbeam Software", "engager_company_industry": "Software Development",
        "engager_company_description": "Custom software development agency building products for fintech clients",
        "engager_company_headcount": "21-50", "engager_country": "United Kingdom",
        "engager_linkedin_url": "https://www.linkedin.com/in/fixture-fit-2", "post_url": "p2"}),
    ("miss-title", "OFF_BRIEF", {
        "post_author_name": "Competitor Founder", "post_text": GTM_POST,
        "engagement_type": "like", "comment_text": None,
        "engager_job_title": "Senior Technical Recruiter", "engager_headline": "Hiring GTM talent for scale-ups",
        "engager_company_name": "TalentBridge Recruiting", "engager_company_industry": "Staffing and Recruiting",
        "engager_company_description": "Recruitment agency placing sales and marketing professionals",
        "engager_company_headcount": "51-100", "engager_country": "United States",
        "engager_linkedin_url": "https://www.linkedin.com/in/fixture-miss-title", "post_url": "p3"}),
    ("miss-geo", "OFF_BRIEF", {
        "post_author_name": "Competitor Founder", "post_text": GTM_POST,
        "engagement_type": "comment", "comment_text": "Very insightful sir",
        "engager_job_title": "VP Sales", "engager_headline": "VP Sales",
        "engager_company_name": "GlobalTech Solutions", "engager_company_industry": "IT Services",
        "engager_company_description": "IT services and consulting",
        "engager_company_headcount": "51-100", "engager_country": "India",
        "engager_linkedin_url": "https://www.linkedin.com/in/fixture-miss-geo", "post_url": "p4"}),
    ("miss-topic", "OFF_BRIEF", {
        "post_author_name": "Competitor Founder",
        "post_text": ("10 years ago today I married my best friend. She believed in me through the darkest "
                      "days of building this company. Happy anniversary my love."),
        "engagement_type": "like", "comment_text": None,
        "engager_job_title": "Head of Sales", "engager_headline": "Head of Sales at Nimbus Analytics",
        "engager_company_name": "Nimbus Analytics", "engager_company_industry": "Software Development",
        "engager_company_description": "Product analytics platform for SaaS teams",
        "engager_company_headcount": "101-200", "engager_country": "Canada",
        "engager_linkedin_url": "https://www.linkedin.com/in/fixture-miss-topic", "post_url": "p5"}),
    ("borderline", None, {  # any verdict accepted - reported for calibration
        "post_author_name": "Competitor Founder", "post_text": GTM_POST,
        "engagement_type": "like", "comment_text": None,
        "engager_job_title": "Sales Manager", "engager_headline": "Sales Manager | helping teams hit quota",
        "engager_company_name": "Corvid Consulting", "engager_company_industry": "Business Consulting and Services",
        "engager_company_description": "Consulting firm",
        "engager_company_headcount": "11-20", "engager_country": "United States",
        "engager_linkedin_url": "https://www.linkedin.com/in/fixture-borderline", "post_url": "p6"}),
]


def main():
    if QUALIFY_CACHE.exists():
        shutil.rmtree(QUALIFY_CACHE)  # fixtures must exercise the live path
    fails, llm_calls = [], 0
    for name, expect, event in FIXTURES:
        r = qualify_engager(event, CFG)
        if r["method"] == "llm":
            llm_calls += 1
        ok = expect is None or r["verdict"] == expect
        if not ok:
            fails.append(name)
        print(f"{'PASS' if ok else 'FAIL':4} {name:12} verdict={r['verdict']:10} method={r['method']:11} "
              f"topic={str(r.get('topic'))[:30]!r:34} reason={str(r['reason'])[:60]}")
    geo = qualify_engager(FIXTURES[3][2], CFG)
    gate_ok = geo["method"] == "string-gate"
    print(f"\nLLM calls: {llm_calls} (geo miss used {'string gate - zero tokens' if gate_ok else 'LLM (FAIL)'})")
    if fails or not gate_ok:
        print(f"RESULT: FAIL ({', '.join(fails) or 'string-gate check'})")
        sys.exit(1)
    print("RESULT: PASS")


if __name__ == "__main__":
    main()
