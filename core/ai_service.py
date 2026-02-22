"""
MCS Platform - AI Service Layer (Sprint 1)
Provides AI-powered risk analysis using OpenAI-compatible API.
Features:
  - Tier 3: Contextual Risk Analysis per flag
  - AI Risk Summary Report generation (narrative Word document)
  - AI Smart Flag Prioritisation (ATO Interest scoring)
  - Response caching via data hash to avoid redundant API calls
"""
import hashlib
import json
import io
import logging
from decimal import Decimal

from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OpenAI Client Setup (uses pre-configured env vars)
# ---------------------------------------------------------------------------
def _get_client():
    """Get an OpenAI client configured for the platform."""
    try:
        from openai import OpenAI
        return OpenAI()  # Uses OPENAI_API_KEY and base_url from env
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install openai")


def _call_llm(system_prompt, user_prompt, model="gpt-4.1-mini", temperature=0.3, max_tokens=2000):
    """
    Call the LLM with system and user prompts.
    Returns the response text.
    """
    client = _get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Data Hash for Cache Invalidation
# ---------------------------------------------------------------------------
def _compute_flag_hash(flag):
    """Compute MD5 hash of flag data for cache invalidation."""
    data = {
        "rule_id": flag.rule_id,
        "severity": flag.severity,
        "description": flag.description,
        "calculated_values": _serialise_values(flag.calculated_values),
        "affected_accounts": flag.affected_accounts,
    }
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _serialise_values(obj):
    """Convert Decimal values to float for JSON serialisation."""
    if isinstance(obj, dict):
        return {k: _serialise_values(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialise_values(v) for v in obj]
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj


# ---------------------------------------------------------------------------
# Context Builder — assembles financial data for AI prompts
# ---------------------------------------------------------------------------
def _build_entity_context(financial_year):
    """
    Build a rich context string about the entity and financial year
    for use in AI prompts.
    """
    entity = financial_year.entity
    lines = financial_year.trial_balance_lines.all().order_by("section", "account_code")

    # Basic info
    ctx = f"Entity: {entity.entity_name}\n"
    ctx += f"Type: {entity.get_entity_type_display()}\n"
    ctx += f"ABN: {entity.abn or 'Not provided'}\n"
    ctx += f"Financial Year: {financial_year.year_label} ({financial_year.start_date} to {financial_year.end_date})\n"
    ctx += f"Period Type: {financial_year.get_period_type_display()}\n"
    ctx += f"Status: {financial_year.get_status_display()}\n\n"

    # Trial Balance Summary
    ctx += "=== TRIAL BALANCE ===\n"
    total_revenue = Decimal("0")
    total_expenses = Decimal("0")
    total_assets = Decimal("0")
    total_liabilities = Decimal("0")

    for line in lines:
        balance = line.adjusted_balance or line.original_balance or Decimal("0")
        prior = line.prior_year_balance or Decimal("0")
        variance = balance - prior if prior else None

        ctx += f"  {line.account_code} | {line.account_name} | "
        ctx += f"Current: ${balance:,.2f}"
        if prior:
            ctx += f" | Prior: ${prior:,.2f}"
        if variance is not None and prior:
            pct = (variance / abs(prior) * 100) if prior != 0 else Decimal("0")
            ctx += f" | Var: ${variance:,.2f} ({pct:,.1f}%)"
        ctx += f" | Section: {line.section}\n"

        section = (line.section or "").lower()
        if "revenue" in section or "income" in section:
            total_revenue += balance
        elif "expense" in section or "cost" in section:
            total_expenses += abs(balance)
        elif "asset" in section:
            total_assets += balance
        elif "liabilit" in section:
            total_liabilities += abs(balance)

    ctx += f"\nSummary: Revenue=${total_revenue:,.2f}, Expenses=${total_expenses:,.2f}, "
    ctx += f"Net={total_revenue - total_expenses:,.2f}\n"
    ctx += f"Assets=${total_assets:,.2f}, Liabilities=${total_liabilities:,.2f}\n"

    return ctx


def _build_flag_context(flag):
    """Build context string for a specific risk flag."""
    ctx = f"Risk Flag: {flag.title}\n"
    ctx += f"Rule ID: {flag.rule_id}\n"
    ctx += f"Tier: {flag.tier}\n"
    ctx += f"Severity: {flag.severity}\n"
    ctx += f"Description: {flag.description}\n"
    ctx += f"Recommended Action: {flag.recommended_action}\n"

    if flag.legislation_ref:
        ctx += f"Legislation: {flag.legislation_ref}\n"

    if flag.affected_accounts:
        ctx += f"Affected Accounts: {', '.join(str(a) for a in flag.affected_accounts)}\n"

    if flag.calculated_values:
        ctx += "Calculated Values:\n"
        for k, v in flag.calculated_values.items():
            ctx += f"  {k}: {v}\n"

    return ctx


# ---------------------------------------------------------------------------
# Tier 3: AI Contextual Risk Analysis
# ---------------------------------------------------------------------------
ANALYSIS_SYSTEM_PROMPT = """You are an expert Australian tax and accounting advisor working for MC & S, 
a Melbourne-based accounting practice. You analyse risk flags raised by an automated audit engine 
against financial statements prepared under Australian Accounting Standards (AASB).

Your role is to:
1. Explain the risk in plain English that a CPA-qualified accountant would understand
2. Provide specific, actionable recommendations
3. Reference relevant Australian legislation (ITAA 1936/1997, Corporations Act 2001, SIS Act 1993) where applicable
4. Consider the ATO's current compliance focus areas
5. Be concise but thorough — aim for 3-5 sentences for explanation, 2-4 bullet points for actions

IMPORTANT: You are assisting accountants, not clients. Use professional language.
Do NOT include disclaimers about seeking professional advice — the reader IS the professional."""


def analyse_risk_flag(flag):
    """
    Run AI contextual analysis on a single risk flag.
    Returns dict with success, explanation, suggested_action, data_hash.
    """
    data_hash = _compute_flag_hash(flag)

    # Check cache — skip if already analysed with same data
    if flag.ai_explanation and flag.ai_data_hash == data_hash:
        return {
            "success": True,
            "explanation": flag.ai_explanation,
            "suggested_action": flag.ai_suggested_action,
            "data_hash": data_hash,
            "cached": True,
        }

    entity_context = _build_entity_context(flag.financial_year)
    flag_context = _build_flag_context(flag)

    user_prompt = f"""Analyse the following risk flag for this entity:

{entity_context}

{flag_context}

Provide your response in the following JSON format:
{{
    "explanation": "Plain English explanation of what this risk means and why it matters",
    "suggested_action": "Specific steps the accountant should take to address this risk"
}}

Return ONLY the JSON, no other text."""

    try:
        response_text = _call_llm(ANALYSIS_SYSTEM_PROMPT, user_prompt)

        # Parse JSON response
        # Handle potential markdown code blocks
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        result = json.loads(response_text)

        return {
            "success": True,
            "explanation": result.get("explanation", ""),
            "suggested_action": result.get("suggested_action", ""),
            "data_hash": data_hash,
            "cached": False,
        }

    except json.JSONDecodeError as e:
        logger.warning(f"AI response was not valid JSON: {e}")
        # Fall back to using the raw text
        return {
            "success": True,
            "explanation": response_text[:1000] if response_text else "Analysis completed but response format was unexpected.",
            "suggested_action": "Please review the explanation above and determine appropriate action.",
            "data_hash": data_hash,
            "cached": False,
        }
    except Exception as e:
        logger.exception(f"AI analysis failed for flag {flag.pk}")
        return {
            "success": False,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# AI Smart Flag Prioritisation (ATO Interest Scoring)
# ---------------------------------------------------------------------------
PRIORITISATION_SYSTEM_PROMPT = """You are an expert on ATO (Australian Taxation Office) compliance 
and audit selection criteria. You score risk flags based on how likely they are to attract ATO attention.

Consider:
- ATO's published compliance focus areas (Division 7A, work-related expenses, rental properties, 
  crypto, SMSF compliance, trust distributions, cash economy businesses)
- The materiality of the amounts involved
- Whether the issue represents a pattern vs one-off
- The entity type and its typical ATO audit risk profile
- Current ATO data-matching capabilities

Score from 1-10 where:
1-3: Low ATO interest — routine, immaterial, or well-documented
4-6: Moderate ATO interest — may trigger data-matching or random review
7-8: High ATO interest — likely to attract attention if ATO reviews this entity
9-10: Very high ATO interest — matches known ATO compliance targets

Be realistic and calibrated. Most flags should score 3-6."""


def prioritise_flags(flags, financial_year):
    """
    Score a batch of flags by ATO interest likelihood.
    Processes in batches to manage token limits.
    """
    if not flags:
        return {"success": True, "scored": 0}

    entity_context = _build_entity_context(financial_year)
    scored = 0

    # Process in batches of 10
    batch_size = 10
    for i in range(0, len(flags), batch_size):
        batch = flags[i:i + batch_size]

        flags_text = ""
        for idx, flag in enumerate(batch):
            flags_text += f"\n--- Flag {idx + 1} (ID: {flag.pk}) ---\n"
            flags_text += _build_flag_context(flag)

        user_prompt = f"""Score the following risk flags for ATO interest likelihood.

{entity_context}

{flags_text}

Return a JSON array with one object per flag:
[
    {{
        "flag_id": "<uuid>",
        "score": <1-10>,
        "reasoning": "Brief explanation of why this score"
    }}
]

Return ONLY the JSON array, no other text."""

        try:
            response_text = _call_llm(
                PRIORITISATION_SYSTEM_PROMPT,
                user_prompt,
                max_tokens=3000,
            )

            # Parse JSON
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            results = json.loads(response_text)

            # Map results back to flags
            result_map = {str(r["flag_id"]): r for r in results}

            for flag in batch:
                result = result_map.get(str(flag.pk))
                if result:
                    flag.ato_interest_score = max(1, min(10, int(result["score"])))
                    flag.ato_interest_reasoning = result.get("reasoning", "")
                    flag.save(update_fields=["ato_interest_score", "ato_interest_reasoning"])
                    scored += 1

        except Exception as e:
            logger.exception(f"AI prioritisation batch error: {e}")
            continue

    return {"success": True, "scored": scored}


# ---------------------------------------------------------------------------
# AI Risk Summary Report (Narrative Word Document)
# ---------------------------------------------------------------------------
REPORT_SYSTEM_PROMPT = """You are a senior Australian accounting professional writing an internal 
risk assessment report for a financial year. The report is for the review partner/manager at MC & S.

Write in a professional but accessible tone. Structure the report as:
1. Executive Summary (2-3 sentences)
2. Key Findings (the most important risks, grouped by theme)
3. Compliance Status (overall assessment of ATO compliance posture)
4. Recommended Actions (prioritised list)
5. Conclusion

Use Australian accounting terminology. Reference specific account balances and variances.
Be specific — don't just repeat the flag descriptions, synthesise them into a coherent narrative."""


def generate_risk_summary_report(financial_year):
    """
    Generate a narrative AI Risk Summary Report as a Word document.
    Returns bytes of the .docx file.
    """
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    entity = financial_year.entity
    flags = financial_year.risk_flags.all().order_by("-severity", "-ato_interest_score")

    # Build the AI prompt
    entity_context = _build_entity_context(financial_year)

    flags_text = ""
    for flag in flags:
        flags_text += f"\n--- [{flag.severity}] {flag.title} ---\n"
        flags_text += f"Status: {flag.status}\n"
        flags_text += f"Description: {flag.description}\n"
        if flag.ai_explanation:
            flags_text += f"AI Analysis: {flag.ai_explanation}\n"
        if flag.ato_interest_score:
            flags_text += f"ATO Interest Score: {flag.ato_interest_score}/10\n"
        if flag.resolution_notes:
            flags_text += f"Resolution: {flag.resolution_notes}\n"

    user_prompt = f"""Write a risk assessment report for this entity and financial year.

{entity_context}

=== RISK FLAGS ({flags.count()} total) ===
{flags_text}

Open flags: {flags.filter(status='open').count()}
Resolved flags: {flags.filter(status__in=['resolved', 'auto_resolved']).count()}
Reviewed flags: {flags.filter(status='reviewed').count()}

Write the full report now. Use markdown-style headers (## for sections)."""

    try:
        report_text = _call_llm(
            REPORT_SYSTEM_PROMPT,
            user_prompt,
            max_tokens=4000,
            temperature=0.4,
        )
    except Exception as e:
        logger.exception("AI report generation failed")
        report_text = (
            f"## Risk Summary Report\n\n"
            f"AI report generation failed: {str(e)}\n\n"
            f"Please review the {flags.count()} risk flags manually."
        )

    # Build Word document
    doc = Document()

    # Title
    title = doc.add_heading(f"Risk Assessment Report", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Subtitle
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(f"{entity.entity_name} — {financial_year.year_label}")
    run.font.size = Pt(14)
    run.font.color.rgb = RGBColor(0x44, 0x44, 0x44)

    # Metadata
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    from django.utils import timezone
    run = meta.add_run(f"Generated: {timezone.now().strftime('%d %B %Y at %H:%M')}")
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    doc.add_paragraph()  # Spacer

    # Summary stats table
    table = doc.add_table(rows=1, cols=4)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text = "Total Flags"
    hdr[1].text = "Open"
    hdr[2].text = "Resolved"
    hdr[3].text = "Avg ATO Score"

    row = table.add_row().cells
    row[0].text = str(flags.count())
    row[1].text = str(flags.filter(status="open").count())
    row[2].text = str(flags.filter(status__in=["resolved", "auto_resolved"]).count())

    scored_flags = flags.exclude(ato_interest_score=None)
    if scored_flags.exists():
        avg_score = sum(f.ato_interest_score for f in scored_flags) / scored_flags.count()
        row[3].text = f"{avg_score:.1f}/10"
    else:
        row[3].text = "N/A"

    doc.add_paragraph()  # Spacer

    # Parse and add the AI-generated report text
    for line in report_text.split("\n"):
        line = line.strip()
        if not line:
            doc.add_paragraph()
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith("- ") or line.startswith("* "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif line.startswith("1. ") or line.startswith("2. ") or line.startswith("3. "):
            doc.add_paragraph(line[3:], style="List Number")
        else:
            # Handle bold text
            p = doc.add_paragraph()
            parts = line.split("**")
            for i, part in enumerate(parts):
                run = p.add_run(part)
                if i % 2 == 1:  # Odd indices are bold
                    run.bold = True

    # Footer
    doc.add_paragraph()
    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("This report was generated by StatementHub AI Risk Engine")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0xAA, 0xAA, 0xAA)
    run = footer.add_run("\nMC & S Accounting — Confidential")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0xAA, 0xAA, 0xAA)

    # Save to bytes
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
