import hashlib
import html
import imaplib
import logging
import re
import smtplib
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr, parsedate_to_datetime
from app.core.config import settings
from app.core.errors import AppError

log = logging.getLogger("email")
MAX_FETCH = 50
MAX_BODY = 6000

QUOTE_START = re.compile(
    r"(?m)^On\s[^\n]*(?:\n[^\n]*)?\bwrote:\s*$|^-{2,}\s*Original Message\s*-{2,}|^From:\s.+\n(?:Sent|Date):"
)
BOUNCE_SUBJECT = re.compile(r"undeliver|delivery status notification|delivery failure|returned mail|mail delivery failed", re.I)
AUTO_SUBJECT = re.compile(r"out of office|automatic reply|auto-?reply|away from (the )?office|on vacation", re.I)


def configured():
    return bool(settings.org_email and settings.org_email_password)


def ready_to_send():
    return settings.email_dry_run or configured()


def open_smtp():
    if settings.smtp_port == 465:
        smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30)
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
        smtp.starttls()
    smtp.login(settings.org_email, settings.org_email_password)
    return smtp


def send_email(to, subject, body, in_reply_to=None, references=None):
    domain = settings.org_email.split("@")[-1] if "@" in settings.org_email else "localhost"
    message_id = make_msgid(domain=domain)
    try:
        msg = EmailMessage()
        msg["From"] = formataddr(("AcmeCorp Accounts", settings.org_email or "accounts@localhost"))
        msg["To"] = to
        msg["Subject"] = " ".join(subject.split())[:200]
        msg["Message-ID"] = message_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references
        msg.set_content(body)
    except ValueError:
        raise AppError("The email has an invalid address or header", 400) from None

    if settings.email_dry_run:
        log.info("DRY RUN email to %s: %s", to, msg["Subject"])
        return message_id
    if not configured():
        raise AppError("Email is not configured: set ORG_EMAIL and ORG_EMAIL_PASSWORD in .env", 503)
    try:
        with open_smtp() as smtp:
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as error:
        log.error("SMTP failure: %s", type(error).__name__)
        raise AppError(f"Could not send the email ({type(error).__name__})", 502) from None
    return message_id


def html_to_text(value):
    value = re.sub(r"(?is)<(script|style).*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", value)
    return html.unescape(re.sub(r"<[^>]+>", " ", value))


def part_text(part):
    try:
        return part.get_content()
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", "replace")


def extract_body(msg):
    plain = msg.get_body(preferencelist=("plain",))
    if plain is not None:
        return part_text(plain)
    rich = msg.get_body(preferencelist=("html",))
    return html_to_text(part_text(rich)) if rich is not None else ""


def strip_quoted(text):
    text = text.replace("\r\n", "\n")
    cut = QUOTE_START.search(text)
    if cut:
        text = text[:cut.start()]
    lines = [line for line in text.split("\n") if not line.lstrip().startswith(">")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:MAX_BODY]


def classify(msg, subject, sender):
    local = sender.split("@")[0]
    if msg.get_content_type() == "multipart/report" or local in ("mailer-daemon", "postmaster") or BOUNCE_SUBJECT.search(subject):
        return "bounce"
    auto = str(msg.get("Auto-Submitted", "no")).strip().lower()
    precedence = str(msg.get("Precedence", "")).strip().lower()
    if auto not in ("", "no") or precedence in ("auto_reply", "bulk", "junk") or msg.get("X-Autoreply") or msg.get("X-Autorespond") or AUTO_SUBJECT.search(subject):
        return "auto_reply"
    return "normal"


def parse_message(raw):
    msg = message_from_bytes(raw, policy=policy.default)
    name, address = parseaddr(str(msg.get("From", "")))
    sender = address.strip().lower()
    subject = " ".join(str(msg.get("Subject", "")).split())[:300]
    ids = re.findall(r"<[^>]+>", str(msg.get("Message-ID", "")))
    reply_ids = re.findall(r"<[^>]+>", str(msg.get("In-Reply-To", "")))
    try:
        sent = parsedate_to_datetime(str(msg.get("Date"))).isoformat()
    except (TypeError, ValueError):
        sent = None
    return {
        "message_id": ids[0] if ids else f"<generated-{hashlib.sha1(raw).hexdigest()[:24]}@local>",
        "in_reply_to": reply_ids[0] if reply_ids else None,
        "references": re.findall(r"<[^>]+>", str(msg.get("References", ""))),
        "from_email": sender,
        "from_name": name,
        "subject": subject,
        "date": sent,
        "body": strip_quoted(extract_body(msg)),
        "kind": classify(msg, subject, sender),
    }


def fetch_unseen():
    if not configured():
        raise AppError("Email is not configured: set ORG_EMAIL and ORG_EMAIL_PASSWORD in .env", 503)
    mails = []
    try:
        with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=30) as imap:
            imap.login(settings.org_email, settings.org_email_password)
            imap.select("INBOX")
            _, data = imap.uid("SEARCH", None, "UNSEEN")
            for uid in data[0].split()[-MAX_FETCH:]:
                _, parts = imap.uid("FETCH", uid, "(BODY.PEEK[])")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                if raw:
                    mails.append({**parse_message(raw), "uid": uid.decode()})
    except (imaplib.IMAP4.error, OSError) as error:
        log.error("IMAP failure: %s", type(error).__name__)
        raise AppError(f"Could not read the inbox ({type(error).__name__})", 502) from None
    return mails


def mark_seen(uids):
    if not uids:
        return
    try:
        with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=30) as imap:
            imap.login(settings.org_email, settings.org_email_password)
            imap.select("INBOX")
            for uid in uids:
                imap.uid("STORE", uid, "+FLAGS", "\\Seen")
    except (imaplib.IMAP4.error, OSError) as error:
        log.error("IMAP mark-seen failure: %s", type(error).__name__)