"""
Parse raw MIME email messages into plain dicts.
"""
import email
import email.utils
import email.header
import json
import re
from datetime import datetime, timezone


def decode_header(value: str) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def parse_address(value: str) -> tuple[str, str]:
    """Return (name, addr) from a From/To header value."""
    if not value:
        return ("", "")
    name, addr = email.utils.parseaddr(value)
    return (decode_header(name), addr.lower())


def parse_address_list(value: str) -> list[dict]:
    if not value:
        return []
    pairs = email.utils.getaddresses([value])
    return [{"name": decode_header(n), "addr": a.lower()} for n, a in pairs if a]


def parse_date(value: str) -> str | None:
    """Parse email date header → ISO datetime string (UTC)."""
    if not value:
        return None
    try:
        ts = email.utils.parsedate_to_datetime(value)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def _get_body(msg: email.message.Message) -> tuple[str, str]:
    """Walk MIME parts and return (text, html) — prefers multipart/alternative."""
    text_parts = []
    html_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            if ct == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    text_parts.append(payload.decode(charset, errors="replace"))
            elif ct == "text/html":
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    html_parts.append(payload.decode(charset, errors="replace"))
    else:
        ct = msg.get_content_type()
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(charset, errors="replace")
            if ct == "text/html":
                html_parts.append(body)
            else:
                text_parts.append(body)

    return "\n".join(text_parts), "\n".join(html_parts)


def _get_attachments(msg: email.message.Message) -> list[dict]:
    attachments = []
    if not msg.is_multipart():
        return attachments
    for part in msg.walk():
        disp = str(part.get("Content-Disposition") or "")
        if "attachment" in disp:
            filename = decode_header(part.get_filename() or "attachment")
            filename = filename.replace('\r', '').replace('\n', '').replace('\t', ' ').strip() or "attachment"
            attachments.append({
                "filename": filename,
                "content_type": part.get_content_type(),
                "size": len(part.get_payload(decode=True) or b""),
            })
    return attachments


def extract_attachment_bytes(raw_bytes: bytes, att_index: int) -> tuple[bytes | None, str | None]:
    """Extract attachment bytes by zero-based index. Returns (data, content_type)."""
    msg = email.message_from_bytes(raw_bytes)
    idx = 0
    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                if idx == att_index:
                    return part.get_payload(decode=True), part.get_content_type()
                idx += 1
    return None, None


def snippet_from_text(text: str, max_len: int = 200) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def parse_raw(raw_bytes: bytes) -> dict:
    """Parse raw MIME bytes → structured dict."""
    msg = email.message_from_bytes(raw_bytes)

    from_name, from_addr = parse_address(msg.get("From", ""))
    to_list = parse_address_list(msg.get("To", ""))
    cc_list = parse_address_list(msg.get("Cc", ""))
    body_text, body_html = _get_body(msg)
    attachments = _get_attachments(msg)

    return {
        "message_id": (msg.get("Message-ID") or "").strip(),
        "in_reply_to": (msg.get("In-Reply-To") or "").strip(),
        "references": (msg.get("References") or "").strip(),
        "subject": decode_header(msg.get("Subject", "(no subject)")),
        "from_name": from_name,
        "from_addr": from_addr,
        "to_addrs": json.dumps(to_list),
        "cc_addrs": json.dumps(cc_list),
        "date": parse_date(msg.get("Date", "")),
        "body_text": body_text,
        "body_html": body_html,
        "snippet": snippet_from_text(body_text or re.sub(r'<[^>]+>', ' ', body_html)),
        "has_attachments": 1 if attachments else 0,
        "attachments": attachments,
    }
