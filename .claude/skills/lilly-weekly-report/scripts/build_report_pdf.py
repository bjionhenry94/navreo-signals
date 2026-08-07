"""
build_report_pdf.py — Parameterized weekly campaign report PDF builder.

Models the Cloneify Report template:
- Title + window subtitle
- Numbered campaign sections (Status / Sent / Replies / Reply Rate /
  Positive Replies / Insight) with a horizontal rule between
- "Overall Observations" (bulleted)
- "Recommendations" (numbered)

Used by the lilly-weekly-report skill. Style: letter portrait, monochrome,
no em dashes.

Usage:
    from build_report_pdf import build_weekly_report

    build_weekly_report(
        client="Arnic",
        window_start="2026-05-05",
        window_end="2026-05-12",
        sections=[
            {
                "title": "Arnic - Reconnect Series (8 reactivation campaigns)",
                "status": "Active (launched 4 May, 8 days in)",
                "sent": "15,268",
                "replies": "173",
                "reply_rate": "1.13%",
                "pos_replies": None,
                "pos_reply_rate": None,
                "insight": "Reconnect was the dominant push this week...",
            },
            ...
        ],
        observations=[
            "Best 10-day reply rate: Reconnect: C4 at 1.30%...",
            ...
        ],
        recommendations=[
            "Find the winning magnet inside LinkedIn Followers Soft...",
            ...
        ],
        output_path="/Users/renoo/arnic-weekly-report-2026-05-12.pdf",
    )
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, HRFlowable
)

BLACK = HexColor("#000000")
TEXT = HexColor("#1A1A1A")
MUTED = HexColor("#666666")
THIN = HexColor("#BBBBBB")

PAGE_W, PAGE_H = letter
MARGIN_X = 0.9 * inch
MARGIN_TOP = 0.9 * inch
MARGIN_BOTTOM = 0.85 * inch
FRAME_W = PAGE_W - 2 * MARGIN_X
FRAME_H = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM


def _styles():
    base, bold = "Helvetica", "Helvetica-Bold"
    return {
        "title": ParagraphStyle(
            "title", fontName=bold, fontSize=24, leading=30,
            textColor=BLACK, alignment=TA_LEFT, spaceAfter=4),
        "subtitle": ParagraphStyle(
            "subtitle", fontName=base, fontSize=11, leading=14,
            textColor=MUTED, alignment=TA_LEFT, spaceAfter=18),
        "section": ParagraphStyle(
            "section", fontName=bold, fontSize=14, leading=18,
            textColor=BLACK, alignment=TA_LEFT, spaceBefore=10, spaceAfter=8),
        "h_overall": ParagraphStyle(
            "h_overall", fontName=bold, fontSize=18, leading=22,
            textColor=BLACK, alignment=TA_LEFT, spaceBefore=18, spaceAfter=8),
        "body": ParagraphStyle(
            "body", fontName=base, fontSize=10.5, leading=14,
            textColor=TEXT, alignment=TA_LEFT, spaceAfter=6),
        "bullet": ParagraphStyle(
            "bullet", fontName=base, fontSize=10.5, leading=14,
            textColor=TEXT, leftIndent=16, bulletIndent=4, spaceAfter=2),
        "insight": ParagraphStyle(
            "insight", fontName=base, fontSize=10.5, leading=14,
            textColor=TEXT, alignment=TA_LEFT, spaceBefore=6, spaceAfter=8),
    }


def _strip_em_dashes(s):
    """Hard rule from lilly-bot: no em dashes. Replace any that slip through."""
    if not isinstance(s, str):
        return s
    return s.replace("—", " - ").replace("–", " - ")


def _bullet(text, style):
    return Paragraph(f"&bull;&nbsp;&nbsp;{_strip_em_dashes(text)}", style)


def _section_block(num, sec, S):
    out = []
    title = _strip_em_dashes(sec["title"])
    out.append(Paragraph(f"{num}. {title}", S["section"]))

    bullet_lines = [
        f"<b>Status:</b> {_strip_em_dashes(sec['status'])}",
        f"<b>Emails Sent:</b> {sec['sent']}",
        f"<b>Replies:</b> {sec['replies']} &rarr; "
        f"<b>Reply Rate:</b> {sec['reply_rate']}",
    ]
    if sec.get("pos_replies") not in (None, ""):
        bullet_lines.append(
            f"<b>Positive Replies:</b> {sec['pos_replies']} &rarr; "
            f"<b>Positive Reply Rate:</b> {sec.get('pos_reply_rate', '')}"
        )

    for line in bullet_lines:
        out.append(_bullet(line, S["bullet"]))

    insight = _strip_em_dashes(sec["insight"])
    out.append(Paragraph(f"<b>Insight:</b> {insight}", S["insight"]))
    out.append(HRFlowable(width="100%", thickness=0.4, color=THIN,
                          spaceBefore=2, spaceAfter=10))
    return out


def _page_chrome_factory(client, window_start, window_end):
    label = (f"{client} - Weekly Performance Report  |  "
             f"{window_start} to {window_end}")
    label = _strip_em_dashes(label)

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(MARGIN_X, 0.5 * inch, label)
        canvas.drawRightString(PAGE_W - MARGIN_X, 0.5 * inch,
                               f"{canvas.getPageNumber()}")
        canvas.restoreState()
    return draw


def build_weekly_report(
    client,
    window_start,
    window_end,
    sections,
    observations,
    recommendations,
    output_path,
    expected_revenue_line=None,
    recommendations_heading="What we're doing this week",
):
    """Build the weekly performance report PDF.

    Args:
        client: Client name, e.g. "Arnic".
        window_start: ISO YYYY-MM-DD start of the reporting window.
        window_end: ISO YYYY-MM-DD end of the reporting window.
        sections: List of dicts. Each dict must contain:
            title, status, sent, replies, reply_rate, insight.
            Optional: pos_replies, pos_reply_rate.
        observations: List of strings, rendered as bullets.
        recommendations: List of strings, rendered as numbered items.
            Each string should NOT include its own number prefix.
        output_path: Absolute path for the output PDF.
        expected_revenue_line: Optional string e.g.
            "Expected Revenue: $X (LTV $Y x N positive responses)".
        recommendations_heading: Heading for the recommendations block.
            Default "What we're doing this week" uses agency voice (DFY
            clients). For Done-With-You clients, override to e.g.
            "Recommended actions for this week" and frame each item as
            advisory rather than first-person plural.
    """
    S = _styles()

    doc = BaseDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        title=f"{client} - Weekly Performance Report - {window_end}",
        author="Lilly")

    body_frame = Frame(MARGIN_X, MARGIN_BOTTOM, FRAME_W, FRAME_H,
                       leftPadding=0, bottomPadding=0,
                       rightPadding=0, topPadding=0, showBoundary=0)
    doc.addPageTemplates([PageTemplate(
        id="body", frames=[body_frame],
        onPage=_page_chrome_factory(client, window_start, window_end))])

    story = []
    story.append(Paragraph("Campaign Performance Report", S["title"]))
    story.append(Paragraph(
        f"Reporting window: {window_start} to {window_end}", S["subtitle"]))

    for i, sec in enumerate(sections, 1):
        story.extend(_section_block(i, sec, S))

    story.append(Paragraph("Overall Observations", S["h_overall"]))
    for obs in observations:
        story.append(_bullet(obs, S["bullet"]))

    if expected_revenue_line:
        story.append(_bullet(
            f"<b>{_strip_em_dashes(expected_revenue_line)}</b>", S["bullet"]))

    story.append(Paragraph(recommendations_heading, S["h_overall"]))
    for idx, rec in enumerate(recommendations, 1):
        rec_clean = _strip_em_dashes(rec)
        story.append(Paragraph(f"{idx}. {rec_clean}", S["body"]))

    doc.build(story)
    return output_path


if __name__ == "__main__":
    # Smoke test
    sample = build_weekly_report(
        client="Arnic",
        window_start="2026-05-05",
        window_end="2026-05-12",
        sections=[
            {
                "title": "Arnic - Reconnect Series (8 campaigns)",
                "status": "Active",
                "sent": "15,268",
                "replies": "173",
                "reply_rate": "1.13%",
                "pos_replies": None, "pos_reply_rate": None,
                "insight": "Reconnect was the dominant push this week...",
            },
            {
                "title": "Arnic - LinkedIn Followers - Soft (8-magnet test)",
                "status": "Active",
                "sent": "2,651",
                "replies": "10",
                "reply_rate": "0.38%",
                "pos_replies": "2", "pos_reply_rate": "20.00%",
                "insight": "Reply rate is low but positive-of-replies is 20%...",
            },
        ],
        observations=[
            "Best 10-day reply rate: Reconnect: C4 Partner-Focused at 1.30%.",
            "Confirmed positive replies: 2 in LinkedIn Followers Soft.",
        ],
        recommendations=[
            "We're pulling per-variant data this week to identify the winning "
            "magnet inside LinkedIn Followers Soft.",
            "We're continuing the Reconnect push and planning a second wave "
            "for next week.",
        ],
        output_path="/tmp/sample-weekly-report.pdf",
    )
    print(f"Wrote {sample}")
