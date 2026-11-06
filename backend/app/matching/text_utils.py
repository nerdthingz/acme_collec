import re
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

NOISE = {
    "NEFT", "RTGS", "IMPS", "UPI", "SWIFT", "SEPA", "CR", "DR", "PVT", "PRIVATE", "LTD",
    "LIMITED", "LLP", "INC", "GMBH", "CO", "CORP", "THE", "AND", "TO", "FROM", "BY",
    "PAYMENT", "PART", "DUES", "INV", "INVOICE", "RE", "REF", "TRANSFER",
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "SEPT", "OCT", "NOV", "DEC",
}

INVOICE_REF = re.compile(
    r"\b(?:INV(?:OICE)?S?|RE|REF)[\s.\-_#:/]*(\d{3,6}(?:\s*[,/&]\s*\d{3,6})*)\b", re.I
)


def clean_text(text):
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def squash(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def name_tokens(text):
    return [
        t for t in clean_text(text).split()
        if t not in NOISE and len(t) > 1 and not any(c.isdigit() for c in t)
    ]


def extract_invoice_numbers(text):
    found = []
    for group in INVOICE_REF.findall(text):
        for digits in re.findall(r"\d+", group):
            number = f"INV-{digits}"
            if number not in found:
                found.append(number)
    return found


def is_subsequence(short, long):
    chars = iter(long)
    return all(c in chars for c in short)


def token_match(a, b):
    if a == b:
        return True
    if min(len(a), len(b)) >= 3:
        if a.startswith(b) or b.startswith(a):
            return True
        if a[0] == b[0] and is_subsequence(a, b):
            return True
    return JaroWinkler.normalized_similarity(a, b) >= 0.9


def name_score(narration_tokens, customer_tokens):
    if not narration_tokens or not customer_tokens:
        return 0.0
    ratio = fuzz.token_set_ratio(" ".join(narration_tokens), " ".join(customer_tokens)) / 100
    matched = sum(any(token_match(n, c) for c in customer_tokens) for n in narration_tokens)
    return 0.5 * ratio + 0.5 * matched / len(narration_tokens)