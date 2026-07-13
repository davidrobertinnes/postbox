"""
Send email via SMTP.
"""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate, make_msgid
from email.header import Header

from core.credentials import get_password


def send_message(
    account: dict,
    to: str | list[str],
    subject: str,
    body: str,
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    reply_to_msg_id: str | None = None,
    references: str | None = None,
    body_html: str | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
    request_receipt: bool = False,
) -> tuple[bool, str]:
    """
    Send a message via SMTP. Returns (ok, message).
    attachments: list of (filename, content_type, bytes)
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

    to_list  = [to]  if isinstance(to,  str) else (to  or [])
    cc_list  = [cc]  if isinstance(cc,  str) else (cc  or [])
    bcc_list = [bcc] if isinstance(bcc, str) else (bcc or [])
    all_rcpt = to_list + cc_list + bcc_list

    # Build body part
    if body_html:
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(body, "plain", "utf-8"))
        body_part.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        body_part = MIMEText(body, "plain", "utf-8")

    # Wrap in multipart/mixed when there are attachments
    if attachments:
        msg = MIMEMultipart("mixed")
        msg.attach(body_part)
        for filename, content_type, data in attachments:
            maintype, subtype = (content_type.split("/", 1) if "/" in content_type
                                 else ("application", "octet-stream"))
            part = MIMEBase(maintype, subtype)
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment",
                            filename=Header(filename, "utf-8").encode())
            msg.attach(part)
    else:
        msg = body_part

    msg["From"]    = f"{account.get('name', '')} <{account['email']}>"
    msg["To"]      = ", ".join(to_list)
    if cc_list:
        msg["Cc"]  = ", ".join(cc_list)
    msg["Subject"] = Header(subject, "utf-8")
    msg["Date"]    = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    if reply_to_msg_id:
        msg["In-Reply-To"] = reply_to_msg_id
        msg["References"]  = f"{references} {reply_to_msg_id}".strip() if references else reply_to_msg_id

    if request_receipt:
        msg["Disposition-Notification-To"] = account["email"]

    try:
        port     = int(account.get("smtp_port", 587))
        host     = account["smtp_host"]
        use_ssl  = bool(account.get("smtp_ssl", 0))
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


def send_mdn(account: dict, original_subject: str, original_message_id: str,
             receipt_to: str) -> bool:
    """Send a Message Disposition Notification (RFC 3798 simplified)."""
    from email.mime.multipart import MIMEMultipart as _MP
    from email.mime.text import MIMEText as _MT

    subject = f"Read: {original_subject}"
    human   = (f"This message confirms that your message\n"
               f"  Subject: {original_subject}\n"
               f"was read by {account.get('name', account['email'])} "
               f"<{account['email']}>.")
    machine = (f"Final-Recipient: rfc822; {account['email']}\r\n"
               f"Original-Message-ID: {original_message_id}\r\n"
               f"Disposition: manual-action/MDN-sent-automatically; displayed\r\n")

    outer = _MP("report", **{"report-type": "disposition-notification"})
    outer.attach(_MT(human, "plain", "utf-8"))
    outer.attach(_MT(machine, "plain", "utf-8"))
    outer["From"]       = f"{account.get('name', '')} <{account['email']}>"
    outer["To"]         = receipt_to
    outer["Subject"]    = Header(subject, "utf-8")
    outer["Date"]       = formatdate(localtime=True)
    outer["Message-ID"] = make_msgid()

    ok_sent, _ = send_message(account, receipt_to, subject, human)
    return ok_sent
