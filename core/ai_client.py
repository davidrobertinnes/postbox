"""
Claude API integration for email intelligence features.
"""
import os
import json

try:
    import anthropic as _anthropic
    _ANTHROPIC_OK = True
except ImportError:
    _anthropic = None
    _ANTHROPIC_OK = False

_HAIKU  = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"


def _client():
    if not _ANTHROPIC_OK:
        raise RuntimeError("anthropic package not installed — run: pip install anthropic")
    from core.credentials import get_api_key
    key = get_api_key()
    if not key:
        raise RuntimeError("No Anthropic API key configured — add one in Accounts > AI Settings")
    return _anthropic.Anthropic(api_key=key)


def summarise_thread(messages: list[dict]) -> str:
    """
    Summarise a thread of messages in 2-3 sentences.
    messages: list of {from_name, from_addr, subject, date, body_text}
    """
    if not messages:
        return ""

    thread_text = "\n\n---\n\n".join(
        f"From: {m.get('from_name') or m.get('from_addr', '')}\n"
        f"Date: {m.get('date', '')}\n"
        f"Subject: {m.get('subject', '')}\n\n"
        f"{(m.get('body_text') or '')[:1000]}"
        for m in messages
    )

    prompt = (
        "Summarise the following email thread in 2-3 concise sentences. "
        "Focus on the key topic, any decisions or actions required, and current status. "
        "Be direct — no preamble like 'This thread is about'.\n\n"
        f"{thread_text}"
    )

    try:
        resp = _client().messages.create(
            model=_HAIKU,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        return f"(Summary unavailable: {e})"


def draft_reply(thread: list[dict], user_intent: str, account_name: str = "") -> str:
    """
    Draft a reply based on the thread context and a short user intent.
    Returns the draft body text (plain text, ready to edit).
    """
    if not thread:
        return ""

    latest = thread[-1]
    thread_excerpt = "\n\n---\n\n".join(
        f"From: {m.get('from_name') or m.get('from_addr', '')}\n"
        f"{(m.get('body_text') or '')[:800]}"
        for m in thread[-3:]  # last 3 messages for context
    )

    sender = account_name or "me"
    prompt = (
        f"You are drafting an email reply on behalf of {sender}.\n\n"
        f"Thread context:\n{thread_excerpt}\n\n"
        f"---\n\n"
        f"User's intent for the reply: {user_intent}\n\n"
        "Write a professional, concise reply. "
        "Plain text only — no markdown. "
        "Do not include a subject line. "
        "Start directly with the greeting or first sentence."
    )

    try:
        resp = _client().messages.create(
            model=_SONNET,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        return f"(Draft unavailable: {e})"


_INVOICE_RE      = r'\b(invoice|receipt|payment|order|statement|bill|quote|tax)\b'
_NEWSLETTER_RE   = r'\b(newsletter|digest|weekly|monthly|roundup|unsubscribe|edition)\b'
_MARKETING_RE    = r'\b(sale|offer|deal|discount|promo|coupon|% off|limited time|shop now|buy now)\b'
_SUPPORT_RE      = r'\b(ticket|case|support|help desk|issue|request|inquiry|enquiry)\b'
_NOREPLY_RE      = r'(no.?reply|noreply|do.?not.?reply|mailer|notifications?@|alerts?@|updates?@)'


def _triage_rules(m: dict) -> dict:
    """Rule-based fallback triage — no API key required."""
    import re
    addr    = (m.get('from_addr') or '').lower()
    subject = (m.get('subject')   or '').lower()
    snippet = (m.get('snippet')   or '').lower()
    text    = subject + ' ' + snippet

    if re.search(_NOREPLY_RE, addr, re.I):
        category, priority = 'notification', 3
    elif re.search(_INVOICE_RE, text, re.I):
        category, priority = 'invoice', 1
    elif re.search(_SUPPORT_RE, text, re.I):
        category, priority = 'support', 2
    elif re.search(_NEWSLETTER_RE, text, re.I):
        category, priority = 'newsletter', 3
    elif re.search(_MARKETING_RE, text, re.I):
        category, priority = 'marketing', 3
    else:
        category, priority = 'personal', 2

    return {'id': m['id'], 'priority': priority, 'category': category}


def triage_messages(messages: list[dict]) -> list[dict]:
    """
    Batch-triage a list of message dicts (id, from_addr, subject, snippet).
    Returns list of {id, priority, category}.
    priority: 1=urgent/action-required, 2=normal, 3=low/marketing
    category: invoice|support|personal|newsletter|marketing|notification|other
    """
    if not messages:
        return []

    # Fall back to rules if no API key is set
    try:
        _client()
    except RuntimeError:
        return [_triage_rules(m) for m in messages]

    items = "\n".join(
        f"[{i}] from={m.get('from_addr') or ''} "
        f"subject={repr(m.get('subject') or '')} "
        f"preview={(m.get('snippet') or '')[:120]}"
        for i, m in enumerate(messages)
    )

    prompt = (
        "Triage these emails. For each, assign:\n"
        "- priority: 1=urgent/needs action, 2=normal, 3=low/marketing/newsletter\n"
        "- category: invoice|support|personal|newsletter|marketing|notification|other\n\n"
        "Respond with a JSON array in the same order as the input:\n"
        "[{\"priority\":1,\"category\":\"invoice\"}, ...]\n\n"
        f"Emails:\n{items}\n\nJSON only."
    )

    try:
        resp = _client().messages.create(
            model=_HAIKU,
            max_tokens=len(messages) * 30 + 128,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = json.loads(resp.content[0].text.strip())
        return [
            {
                "id": messages[i]["id"],
                "priority": int(r.get("priority", 2)),
                "category": str(r.get("category", "other")),
            }
            for i, r in enumerate(raw)
            if i < len(messages)
        ]
    except Exception:
        return []


def extract_actions(thread: list[dict]) -> list[dict]:
    """
    Extract action items, dates, and commitments from a thread.
    Returns list of {type, description, due_date}.
    """
    if not thread:
        return []

    thread_text = "\n\n".join(
        f"{(m.get('body_text') or '')[:600]}"
        for m in thread[-5:]
    )

    prompt = (
        "Extract all action items, commitments, and important dates from this email thread. "
        "Return a JSON array. Each item: {\"type\": \"task|date|commitment\", \"description\": \"...\", \"due_date\": \"YYYY-MM-DD or null\"}. "
        "If none found, return []. Output JSON only — no prose.\n\n"
        f"{thread_text}"
    )

    try:
        resp = _client().messages.create(
            model=_HAIKU,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        return json.loads(text)
    except Exception:
        return []
