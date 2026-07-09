"""
Send email via SMTP.
"""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from email.header import Header

from core.credentials import get_password


def send_message(
    account: dict,
    to: str | list[str],
    subject: str,
    body: str,
    cc: str | list[str] | None = None,
    reply_to_msg_id: str | None = None,
    references: str | None = None,
    body_html: str | None = None,
) -> tuple[bool, str]:
    """
    Send a message via SMTP.
    Returns (ok, message).
    account dict needs: smtp_host, smtp_port, smtp_ssl, username, id
    """
    auth_type = account.get("auth_type", "password")
    password = None
    access_token = None

    if auth_type == "oauth_microsoft":
        try:
            from core.oauth_microsoft import get_valid_access_token
            access_token = get_valid_access_token(account["id"], account.get("email", ""))
        except Exception as e:
            return False, f"OAuth token error: {e}"
    elif auth_type == "oauth_google":
        try:
            from core.oauth_google import get_valid_access_token
            access_token = get_valid_access_token(account["id"], account.get("email", ""))
        except Exception as e:
            return False, f"OAuth token error: {e}"
    else:
        password = get_password(account["id"])
        if not password:
            return False, "No password stored for this account"

    to_list = [to] if isinstance(to, str) else to
    cc_list = [cc] if isinstance(cc, str) else (cc or [])
    all_rcpt = to_list + cc_list

    msg = MIMEMultipart("alternative") if body_html else MIMEText(body, "plain", "utf-8")

    msg["From"] = f"{account.get('name', '')} <{account['email']}>"
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = Header(subject, "utf-8")
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    if reply_to_msg_id:
        msg["In-Reply-To"] = reply_to_msg_id
        msg["References"] = f"{references} {reply_to_msg_id}".strip() if references else reply_to_msg_id

    if body_html:
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        port    = int(account.get("smtp_port", 587))
        host    = account["smtp_host"]
        use_ssl = bool(account.get("smtp_ssl", 0))
        username = account.get("username") or account["email"]

        def _smtp_auth(s):
            if access_token:
                import base64
                raw = f"user={account['email']}\x01auth=Bearer {access_token}\x01\x01"
                encoded = base64.b64encode(raw.encode()).decode()
                code, resp = s.docmd("AUTH", f"XOAUTH2 {encoded}")
                if code != 235:
                    raise smtplib.SMTPAuthenticationError(code, resp)
            else:
                s.login(username, password)

        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
                _smtp_auth(s)
                s.sendmail(account["email"], all_rcpt, msg.as_bytes())
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.ehlo()
                s.starttls()
                s.ehlo()
                _smtp_auth(s)
                s.sendmail(account["email"], all_rcpt, msg.as_bytes())

        return True, "Sent"
    except Exception as e:
        return False, str(e)
