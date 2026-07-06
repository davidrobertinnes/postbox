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
        port = int(account.get("smtp_port", 587))
        host = account["smtp_host"]
        use_ssl = bool(account.get("smtp_ssl", 0))
        username = account.get("username") or account["email"]

        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
                s.login(username, password)
                s.sendmail(account["email"], all_rcpt, msg.as_bytes())
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.ehlo()
                s.starttls()
                s.login(username, password)
                s.sendmail(account["email"], all_rcpt, msg.as_bytes())

        return True, "Sent"
    except Exception as e:
        return False, str(e)
