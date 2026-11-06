from email.message import EmailMessage
import pytest
from app.core.config import settings
from app.integrations.email_client import parse_message
from app.services import collections_service as rules

settings.today = "2026-11-05"

ORG = {
    "name": "AcmeCorp", "accounts_email": "accounts@acme.test", "phone": "+91 80 5550 0142",
    "bank_details": {"account_name": "AcmeCorp", "account_number": "000111222333", "bank": "Example Bank", "ifsc": "EXMP0000142", "swift_code": "EXMPINBBXXX"},
    "policies": {"working_hours": "Monday to Friday, 10:00 to 18:00 IST"},
}
CUSTOMER = {"customer_id": "C002", "name": "Kestrel Foods Private Limited", "contact_name": "Arjun Nair", "contact_email": "arjun@kestrel.test", "currency": "INR"}
OTHER = {"customer_id": "C004", "name": "Saffron Peak Hospitality LLP", "contact_name": "Rohan", "contact_email": "r@saffron.test", "currency": "INR"}


def invoice(number, due, owed, overdue, subtotal=50000.0):
    return {
        "invoice_number": number, "invoice_date": "2026-08-20", "due_date": due, "amount_owed": owed, "is_overdue": overdue,
        "days_overdue": 10 if overdue else 0, "amount_paid": 0.0, "subtotal": subtotal, "currency": "INR", "customer_id": "C002",
    }


INVOICES = [invoice("INV-1004", "2026-09-19", 59000.0, True), invoice("INV-1005", "2026-10-20", 59000.0, True)]


def check(text):
    return rules.validate_draft(text, CUSTOMER, ORG, INVOICES, [CUSTOMER, OTHER])


@pytest.mark.parametrize("amount,currency,expected", [
    (118000, "INR", "₹1,18,000.00"), (236000, "INR", "₹2,36,000.00"), (59000, "INR", "₹59,000.00"),
    (999, "INR", "₹999.00"), (1234567.5, "INR", "₹12,34,567.50"), (12500, "USD", "$12,500.00"),
    (9200, "EUR", "€9,200.00"), (7350.5, "GBP", "£7,350.50"),
])
def test_format_money(amount, currency, expected):
    assert rules.format_money(amount, currency) == expected


def test_format_date_and_names():
    assert rules.format_date("2026-09-19") == "19 September 2026"
    assert rules.first_name("Arjun Nair") == "Arjun"
    assert rules.first_name("Dr. Anil Menon") == "Dr. Menon"


def test_valid_draft_passes():
    text = ("Dear Arjun,\nINV-1004: ₹59,000.00, due 19 September 2026\nINV-1005: ₹59,000.00, due 20 October 2026\n"
            "Total ₹1,18,000.00. Pay to account 000111222333, IFSC EXMP0000142. Contact accounts@acme.test")
    assert check(text) == []


@pytest.mark.parametrize("text", [
    "Total ₹1,17,000.00", "INV-1004 is due 19 October 2026", "Please pay INV-1010", "Pay $59,000.00 now",
    "IFSC HDFC0001234", "Write to bob@evil.test", "Saffron Peak owes money", "Pay into account 999888777666",
    "Due 31/02/2026", "Total 1,18,001",
])
def test_bad_drafts_are_rejected(text):
    assert check(text) != []


def test_feedback_never_names_other_customers():
    problems = check("INV-1010 and Saffron Peak")
    assert "Saffron" not in " ".join(rules.safe_feedback(problems))
    assert "INV-1010" not in " ".join(rules.safe_feedback(problems))


def test_inspect_email_rules():
    by_number = {"INV-1004": {"customer_id": "C002"}, "INV-1010": {"customer_id": "C004"}, "INV-1001": {"customer_id": "C002"}}
    def hit(text):
        found = rules.inspect_email(text, CUSTOMER, [CUSTOMER, OTHER], by_number, {"INV-1004"})
        return found["intent"] if found else None
    assert hit("We will contact our lawyer") == "legal"
    assert hit("This amount is wrong, we dispute it") == "dispute"
    assert hit("Can we get an extension?") == "extension_request"
    assert hit("What does Saffron Peak owe?") == "other_company"
    assert hit("Details of INV-1010 please") == "other_company"
    assert hit("About INV-1001") == "other"
    assert hit("Is this the only amount pending? Send bank details") is None
    assert hit("We paid INV-1004 yesterday") is None


def build(subject="Hello", body="Hi", frm="Arjun <arjun@kestrel.test>", extra=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = frm, "acct@acme.test", subject, "<x@y>"
    for k, v in (extra or {}).items():
        m[k] = v
    m.set_content(body)
    return parse_message(m.as_bytes())


def test_parse_strips_quoted_reply():
    body = "Thanks, will pay Friday.\n\nOn Thu, 5 Nov 2026 at 10:30, AcmeCorp Accounts <a@acme.test> wrote:\n> old text legal action\n"
    parsed = build(body=body)
    assert parsed["body"] == "Thanks, will pay Friday."
    assert parsed["kind"] == "normal"


def test_parse_detects_auto_replies_and_bounces():
    assert build(subject="Automatic reply: away", extra={"Auto-Submitted": "auto-replied"})["kind"] == "auto_reply"
    assert build(subject="Out of Office")["kind"] == "auto_reply"
    assert build(subject="Delivery Status Notification (Failure)", frm="Mail Delivery Subsystem <mailer-daemon@googlemail.com>")["kind"] == "bounce"