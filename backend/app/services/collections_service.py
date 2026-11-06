import re
from datetime import date
from app.core.clock import today
from app.core.config import settings
from app.matching.text_utils import extract_invoice_numbers, name_tokens
from app.services import invoice_service

SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
CODE_OF = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP", "INR": "INR", "USD": "USD", "EUR": "EUR", "GBP": "GBP", "RS": "INR"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
TITLES = {"dr", "mr", "mrs", "ms", "prof"}
AUTO_INTENTS = {"balance_query", "payment_instructions", "payment_claim"}
TDS_RATE = 0.10

LEGAL = re.compile(r"\b(legal|lawyer|attorney|advocate|solicitor|court|sue|suing|lawsuit|litigation|police|fir|consumer forum|arbitration|tribunal|defamation)\b", re.I)
DISPUTE = re.compile(r"\b(disput\w*|incorrect|wrong (amount|invoice|charge)\w*|overcharg\w*|not (ordered|received)|never (ordered|received)|didn'?t (order|receive)|fraud\w*|refund\w*|credit note)\b", re.I)
EXTENSION = re.compile(r"\b(extension|extend\w*|more time|postpon\w*|defer\w*|instal+ments?|reschedul\w*|pay later|can'?t pay|cannot pay|unable to pay|financial (difficult\w*|problem\w*)|waive\w*|waiver|discount|settle(ment)?)\b", re.I)

AMOUNT = re.compile(
    r"(?P<cur>[₹$€£]|\b(?:INR|USD|EUR|GBP|Rs\.?)(?=\s?\d))\s?(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"|(?<![\d,.])(?P<bare>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?)(?![\d,])",
    re.I,
)
DATE_WORDS = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")\s*,?\s*(\d{4})\b", re.I)
DATE_US = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})\b", re.I)
DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DATE_SLASH = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
LONG_DIGITS = re.compile(r"(?<![\d,.])\d{9,18}(?![\d,.])")


def format_money(amount, currency):
    whole, fraction = f"{abs(amount):.2f}".split(".")
    if currency == "INR":
        head, tail, parts = whole[:-3], whole[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail]) if parts else tail
    else:
        whole = f"{int(whole):,}"
    symbol = SYMBOLS.get(currency, currency + " ")
    return f"{'-' if amount < 0 else ''}{symbol}{whole}.{fraction}"


def format_date(value):
    d = value if isinstance(value, date) else date.fromisoformat(value)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def first_name(contact_name):
    parts = (contact_name or "").split()
    if not parts:
        return "Sir/Madam"
    if parts[0].rstrip(".").lower() in TITLES and len(parts) > 1:
        return f"{parts[0]} {parts[-1]}"
    return parts[0]


def open_invoices(customer_id):
    items = [i for i in invoice_service.list_invoices(customer_id=customer_id) if i["amount_owed"] > 0]
    return sorted(items, key=lambda i: (i["due_date"], i["invoice_number"]))


def tds_amount(invoice):
    if invoice["currency"] != "INR" or invoice["amount_paid"] != 0:
        return 0.0
    return round(invoice["subtotal"] * TDS_RATE, 2)


def payment_block(customer, org):
    bank = org["bank_details"]
    if customer["currency"] == "INR":
        return (f"You can pay by NEFT, RTGS, IMPS or UPI to {bank['account_name']}, account {bank['account_number']}, "
                f"{bank['bank']}, IFSC {bank['ifsc']}.")
    methods = "SWIFT or SEPA" if customer["currency"] == "EUR" else "SWIFT"
    return (f"You can pay by {methods} to {bank['account_name']}, account {bank['account_number']}, {bank['bank']}, "
            f"SWIFT code {bank['swift_code']}. Please cover all bank charges on your side so the full invoice amount reaches us.")


def signature(org):
    return f"Regards,\nAccounts Team\n{org['name']}"


def invoice_lines(invoices, currency, with_overdue):
    lines = []
    for i in invoices:
        line = f"- {i['invoice_number']}: {format_money(i['amount_owed'], currency)}, due {format_date(i['due_date'])}"
        if with_overdue and i["is_overdue"]:
            line += f" ({i['days_overdue']} days overdue)"
        lines.append(line)
    return "\n".join(lines)


def total_of(invoices, currency):
    return format_money(round(sum(i["amount_owed"] for i in invoices), 2), currency)


def reminder_email(customer, overdue, org):
    currency = customer["currency"]
    numbers = ", ".join(i["invoice_number"] for i in overdue)
    body = (
        f"Dear {first_name(customer['contact_name'])},\n\n"
        f"This is a reminder that the following {'invoice is' if len(overdue) == 1 else 'invoices are'} overdue:\n\n"
        f"{invoice_lines(overdue, currency, True)}\n\n"
        f"Total overdue: {total_of(overdue, currency)}\n\n"
        f"{payment_block(customer, org)}\n\n"
        f"If you have already paid, please reply with the payment reference and we will check it.\n\n"
        f"{signature(org)}"
    )
    return f"Payment reminder: {numbers} overdue", body


def statement_draft(customer, invoices, org):
    currency = customer["currency"]
    if not invoices:
        middle = "We have no outstanding invoices on your account at the moment."
    else:
        middle = (f"Your outstanding {'invoice is' if len(invoices) == 1 else 'invoices are'}:\n\n"
                  f"{invoice_lines(invoices, currency, False)}\n\nTotal outstanding: {total_of(invoices, currency)}\n\n"
                  f"{payment_block(customer, org)}")
    return f"Dear {first_name(customer['contact_name'])},\n\n{middle}\n\n{signature(org)}"


def holding_draft(kind, customer, org):
    greeting = f"Dear {first_name(customer['contact_name'])}," if customer else "Dear Sir/Madam,"
    hours = org["policies"]["working_hours"]
    texts = {
        "extension_request": f"Thank you for your message. Only our Accounts Team can agree to a different payment date or an instalment plan. We have passed your request to them and they will get back to you. Our team is available {hours}.",
        "dispute": "Thank you for your message. Disputed invoices are reviewed by our Accounts Team within 3 working days. We have passed your message to them and they will respond to you.",
        "legal": "Thank you for your message. We have passed it to our Accounts Team, who will review it and respond to you.",
        "other_company": f"Thank you for your message. We can only discuss an account with its registered contact, so we are unable to share information about other companies. Please contact us from the registered email address of the account concerned, or call {org['phone']}.",
        "unknown_sender": f"Thank you for your message. We could not match this email address to a registered contact, so we are unable to share account information. Please write from the registered email address of your company, or call {org['phone']}. Our team is available {hours}.",
        "payment_claim": "Thank you for letting us know. We have noted your message, and your invoice will be updated once the payment is confirmed in our bank account.",
    }
    text = texts.get(kind, "Thank you for your message. We have passed it to our Accounts Team, who will review it and respond to you.")
    return f"{greeting}\n\n{text}\n\n{signature(org)}"


def build_facts(customer, org, invoices):
    currency = customer["currency"]
    items = []
    for i in invoices:
        item = {
            "invoice_number": i["invoice_number"],
            "balance_due": format_money(i["amount_owed"], currency),
            "invoice_date": format_date(i["invoice_date"]),
            "due_date": format_date(i["due_date"]),
            "status": f"overdue by {i['days_overdue']} days" if i["is_overdue"] else "not yet due",
        }
        if i.get("po_number"):
            item["po_number"] = i["po_number"]
        tds = tds_amount(i)
        if tds:
            item["tds_amount"] = format_money(tds, currency)
            item["payable_if_tds_deducted"] = format_money(round(i["amount_owed"] - tds, 2), currency)
        items.append(item)
    overdue = [i for i in invoices if i["is_overdue"]]
    return {
        "today": format_date(today()),
        "organization": {
            "name": org["name"], "accounts_email": org["accounts_email"], "phone": org["phone"],
            "working_hours": org["policies"]["working_hours"], "payment_methods": org["payment_methods"],
            "bank_details": org["bank_details"], "policies": org["policies"],
        },
        "customer": {
            "contact_first_name": first_name(customer["contact_name"]), "company": customer["name"],
            "country": customer["country"], "currency": currency,
        },
        "open_invoices": items,
        "total_outstanding": total_of(invoices, currency),
        "total_overdue": total_of(overdue, currency),
    }


def other_brands(customer, customers):
    own = set(name_tokens(customer["name"])) if customer else set()
    brands = {}
    for other in customers:
        if customer and other["customer_id"] == customer["customer_id"]:
            continue
        tokens = name_tokens(other["name"])
        if tokens and len(tokens[0]) >= 4 and tokens[0] not in own:
            brands[tokens[0]] = other["name"]
    return brands


def mentions_brand(text, brands):
    upper = text.upper()
    return [name for token, name in brands.items() if re.search(rf"\b{re.escape(token)}\b", upper)]


def inspect_email(text, customer, customers, invoices_by_number, open_numbers):
    if LEGAL.search(text):
        return {"intent": "legal", "reason": "Mentions legal action or lawyers"}
    if DISPUTE.search(text):
        return {"intent": "dispute", "reason": "Looks like a dispute or complaint"}
    if EXTENSION.search(text):
        return {"intent": "extension_request", "reason": "Asks for more time, instalments, a waiver or a discount"}
    others = mentions_brand(text, other_brands(customer, customers))
    foreign = [n for n in extract_invoice_numbers(text)
               if n in invoices_by_number and invoices_by_number[n]["customer_id"] != customer["customer_id"]]
    if others or foreign:
        return {"intent": "other_company", "reason": "Refers to another company or another company's invoice"}
    closed = [n for n in extract_invoice_numbers(text) if n in invoices_by_number and n not in open_numbers]
    if closed:
        return {"intent": "other", "reason": f"Mentions {', '.join(closed)}, which is not an open invoice"}
    return None


def safe_date(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_dates(text):
    found = []
    for d, month, y in DATE_WORDS.findall(text):
        found.append(safe_date(int(y), MONTHS.index(month.capitalize()) + 1, int(d)))
    for month, d, y in DATE_US.findall(text):
        found.append(safe_date(int(y), MONTHS.index(month.capitalize()) + 1, int(d)))
    for y, m, d in DATE_ISO.findall(text):
        found.append(safe_date(int(y), int(m), int(d)))
    for d, m, y in DATE_SLASH.findall(text):
        found.append(safe_date(int(y), int(m), int(d)))
    return found


def safe_feedback(problems):
    result = []
    for problem in problems:
        if problem.startswith("mentions another customer"):
            result.append("it mentioned another customer, which is never allowed")
        elif "is not one of this customer's open invoices" in problem:
            result.append("it mentioned an invoice that is not listed in FACTS")
        else:
            result.append(problem)
    return list(dict.fromkeys(result))


def validate_draft(text, customer, org, invoices, customers):
    problems = []
    currency = customer["currency"]
    allowed_numbers = {i["invoice_number"] for i in invoices}
    for number in extract_invoice_numbers(text):
        if number not in allowed_numbers:
            problems.append(f"{number} is not one of this customer's open invoices")

    allowed_amounts = {round(sum(i["amount_owed"] for i in invoices), 2), round(sum(i["amount_owed"] for i in invoices if i["is_overdue"]), 2)}
    for i in invoices:
        allowed_amounts.add(round(i["amount_owed"], 2))
        tds = tds_amount(i)
        if tds:
            allowed_amounts.update({tds, round(i["amount_owed"] - tds, 2)})
    for match in AMOUNT.finditer(text):
        raw = match.group("num") or match.group("bare")
        value = round(float(raw.rstrip(",").replace(",", "")), 2)
        code = CODE_OF.get((match.group("cur") or "").upper().rstrip(".")) if match.group("cur") else None
        if code and code != currency:
            problems.append(f"amount {match.group(0).strip()} uses {code} but the customer is billed in {currency}")
        elif value not in allowed_amounts:
            problems.append(f"amount {match.group(0).strip()} does not match the records")

    allowed_dates = {today()}
    for i in invoices:
        allowed_dates.update({date.fromisoformat(i["invoice_date"]), date.fromisoformat(i["due_date"])})
    for found in parse_dates(text):
        if found is None or found not in allowed_dates:
            problems.append(f"date {found.isoformat() if found else '(invalid)'} does not match the records")

    bank = org["bank_details"]
    for digits in LONG_DIGITS.findall(text):
        if digits != bank["account_number"]:
            problems.append("contains an account-like number that is not AcmeCorp's")
    for code in IFSC.findall(text):
        if code != bank["ifsc"]:
            problems.append(f"IFSC {code} does not match the records")

    allowed_emails = {e.lower() for e in (org["accounts_email"], settings.org_email, customer["contact_email"]) if e}
    for address in EMAIL.findall(text):
        if address.lower() not in allowed_emails:
            problems.append(f"email address {address} is not a known address")

    leaked = mentions_brand(text, other_brands(customer, customers))
    if leaked:
        problems.append(f"mentions another customer ({', '.join(leaked)})")
    return list(dict.fromkeys(problems))