import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from pymongo.errors import DuplicateKeyError
from app.core.config import settings
from app.core.errors import AppError
from app.integrations import email_client, llm_client
from app.repositories import collections_repo as repo
from app.repositories import customer_repo, invoice_repo, organization_repo
from app.services import collections_service as rules
from app.services import invoice_service

log = logging.getLogger("agent")
inbox_lock = threading.Lock()
MIN_CONFIDENCE = 0.7
LOOP_LIMIT = 5


def now_iso():
    return repo.now_iso()


def new_message(conversation, **fields):
    return {
        "id": uuid.uuid4().hex[:14], "conversation_id": conversation["conversation_id"],
        "customer_id": conversation.get("customer_id"), "created_at": now_iso(), **fields,
    }


def get_conversation_for_customer(customer):
    existing = repo.customer_conversation(customer["customer_id"])
    if existing:
        return existing
    return repo.create_conversation({
        "conversation_id": uuid.uuid4().hex[:12], "kind": "customer", "customer_id": customer["customer_id"],
        "customer_name": customer["name"], "sender_email": None, "created_at": now_iso(),
        "last_message_at": now_iso(), "last_snippet": "", "message_count": 0, "needs_attention": False,
        "delivery_issue": False, "payment_claims": [],
    })


def get_conversation_for_sender(sender_email, sender_name):
    existing = repo.sender_conversation(sender_email)
    if existing:
        return existing
    return repo.create_conversation({
        "conversation_id": uuid.uuid4().hex[:12], "kind": "unknown", "customer_id": None,
        "customer_name": sender_name or sender_email, "sender_email": sender_email, "created_at": now_iso(),
        "last_message_at": now_iso(), "last_snippet": "", "message_count": 0, "needs_attention": False,
        "delivery_issue": False, "payment_claims": [],
    })


def refresh_attention_flag(conversation_id):
    repo.update_conversation(conversation_id, {"needs_attention": repo.open_attention_count(conversation_id) > 0})


def send_reminders(customer_id=None, force=False):
    if not email_client.ready_to_send():
        raise AppError("Email is not configured: set ORG_EMAIL and ORG_EMAIL_PASSWORD in .env", 503)
    repo.ensure_indexes()
    org = organization_repo.get()
    customers = customer_repo.list_all()
    if customer_id and not any(c["customer_id"] == customer_id for c in customers):
        raise AppError("Customer not found", 404)
    overdue = invoice_service.list_invoices(customer_id=customer_id, overdue=True)
    cooldown = timedelta(days=settings.reminder_cooldown_days)
    results = []
    for customer in customers:
        if customer_id and customer["customer_id"] != customer_id:
            continue
        mine = sorted((i for i in overdue if i["customer_id"] == customer["customer_id"]), key=lambda i: (i["due_date"], i["invoice_number"]))
        if not mine:
            if customer_id:
                results.append({"customer_id": customer["customer_id"], "status": "skipped", "reason": "No overdue invoices"})
            continue
        last = repo.last_reminder(customer["customer_id"])
        if last and not force and datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"]) < cooldown:
            results.append({"customer_id": customer["customer_id"], "status": "skipped", "reason": f"Reminded within the last {settings.reminder_cooldown_days} days"})
            continue
        subject, body = rules.reminder_email(customer, mine, org)
        try:
            message_id = email_client.send_email(customer["contact_email"], subject, body)
        except AppError as error:
            results.append({"customer_id": customer["customer_id"], "status": "failed", "reason": error.message})
            continue
        conversation = get_conversation_for_customer(customer)
        repo.add_message(new_message(
            conversation, direction="outbound", kind="reminder", message_id=message_id,
            from_email=settings.org_email, to_email=customer["contact_email"], subject=subject, body=body,
            invoice_numbers=[i["invoice_number"] for i in mine], status="sent",
        ))
        results.append({"customer_id": customer["customer_id"], "status": "sent", "to": customer["contact_email"],
                        "invoices": [i["invoice_number"] for i in mine]})
    return results


def identify_sender(mail, customers):
    matches = [c for c in customers if (c["contact_email"] or "").strip().lower() == mail["from_email"]]
    parent = repo.find_by_email_ids([mail["in_reply_to"], *reversed(mail["references"])])
    if len(matches) == 1:
        return matches[0], parent, None
    if len(matches) > 1:
        for customer in matches:
            if parent and parent.get("customer_id") == customer["customer_id"]:
                return customer, parent, None
        return None, parent, "The sender address matches several customers and the thread does not say which"
    return None, parent, "The sender is not a registered customer contact"


def locate_conversation(mail, customer, parent):
    if customer:
        return get_conversation_for_customer(customer)
    if parent and parent.get("customer_id"):
        existing = repo.get_conversation(parent["conversation_id"])
        if existing:
            return existing
    return get_conversation_for_sender(mail["from_email"], mail["from_name"])


def reply_subject(subject):
    return subject if subject.lower().startswith("re:") else f"Re: {subject or 'your message'}"


def thread_references(mail):
    return " ".join([*mail["references"], mail["message_id"]])[-900:]


def flag(inbound, conversation, reason, intent, draft, problems=None, analysis=None):
    fields = {
        "intent": intent,
        "attention": {"status": "open", "reason": reason, "draft": draft, "problems": problems or []},
    }
    if analysis:
        fields.update({"confidence": analysis.confidence, "summary": analysis.summary})
    repo.update_message(inbound["id"], fields)
    repo.update_conversation(conversation["conversation_id"], {"needs_attention": True})
    return "needs_attention"


def note_claim(conversation, inbound, analysis, open_numbers):
    mentioned = [n for n in analysis.mentioned_invoices if n in open_numbers]
    repo.update_conversation(conversation["conversation_id"], push={"payment_claims": {
        "message_id": inbound["id"], "noted_at": now_iso(), "summary": analysis.summary[:300],
        "invoices": mentioned, "verified": False,
    }})


def decide(mail, inbound, conversation, customer, customers, org):
    invoices = rules.open_invoices(customer["customer_id"])
    open_numbers = {i["invoice_number"] for i in invoices}
    by_number = {i["invoice_number"]: i for i in invoice_repo.find({})}
    text = f"{mail['subject']}\n{mail['body']}"

    hit = rules.inspect_email(text, customer, customers, by_number, open_numbers)
    if hit:
        return flag(inbound, conversation, hit["reason"], hit["intent"], rules.holding_draft(hit["intent"], customer, org))

    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="microseconds")
    if repo.count_auto_answers_since(conversation["conversation_id"], since) >= LOOP_LIMIT:
        return flag(inbound, conversation, "Too many automatic replies in the last hour (possible mail loop)", "other",
                    rules.holding_draft("other", customer, org))

    facts = rules.build_facts(customer, org, invoices)
    problems, analysis = [], None
    for _ in range(2):
        try:
            analysis = llm_client.analyze(facts, mail["subject"], mail["body"], rules.safe_feedback(problems) or None)
        except llm_client.LLMUnavailable as error:
            return flag(inbound, conversation, f"AI unavailable: {error}", "other", rules.statement_draft(customer, invoices, org))
        problems = rules.validate_draft(analysis.reply, customer, org, invoices, customers)
        if not problems:
            break

    intent = analysis.intent
    if intent == "payment_claim":
        note_claim(conversation, inbound, analysis, open_numbers)
    if problems:
        fallback = rules.holding_draft(intent, customer, org) if intent not in rules.AUTO_INTENTS or intent == "payment_claim" else rules.statement_draft(customer, invoices, org)
        return flag(inbound, conversation, "The AI draft did not match the records, so a safe draft is shown instead", intent, fallback, problems, analysis)
    confidence = max(0.0, min(1.0, float(analysis.confidence)))
    if intent not in rules.AUTO_INTENTS:
        return flag(inbound, conversation, f"Needs a person: {intent.replace('_', ' ')}", intent, analysis.reply, None, analysis)
    if confidence < MIN_CONFIDENCE:
        return flag(inbound, conversation, f"Low confidence ({confidence:.2f})", intent, analysis.reply, None, analysis)

    try:
        message_id = email_client.send_email(
            customer["contact_email"], reply_subject(mail["subject"]), analysis.reply,
            in_reply_to=mail["message_id"], references=thread_references(mail),
        )
    except AppError as error:
        return flag(inbound, conversation, f"Could not send the automatic reply: {error.message}", intent, analysis.reply, None, analysis)
    repo.update_message(inbound["id"], {"intent": intent, "confidence": confidence, "summary": analysis.summary})
    repo.add_message(new_message(
        conversation, direction="outbound", kind="auto_answer", message_id=message_id, from_email=settings.org_email,
        to_email=customer["contact_email"], subject=reply_subject(mail["subject"]), body=analysis.reply,
        in_reply_to=mail["message_id"], intent=intent, confidence=confidence, status="sent",
    ))
    return "auto_answered"


def process_mail(mail, customers, org):
    if repo.has_message(mail["message_id"]):
        return "duplicate"
    if settings.org_email and mail["from_email"] == settings.org_email.lower():
        return "ignored"
    customer, parent, unverified_reason = identify_sender(mail, customers)
    conversation = locate_conversation(mail, customer, parent)
    inbound = new_message(
        conversation, direction="inbound", kind="customer" if mail["kind"] == "normal" else mail["kind"],
        message_id=mail["message_id"], in_reply_to=mail["in_reply_to"], references=mail["references"],
        from_email=mail["from_email"], from_name=mail["from_name"], subject=mail["subject"], body=mail["body"],
        sent_at=mail["date"], sender_verified=customer is not None, status="received",
    )
    try:
        repo.add_message(inbound)
    except DuplicateKeyError:
        return "duplicate"

    if mail["kind"] != "normal":
        if mail["kind"] == "bounce":
            repo.update_conversation(conversation["conversation_id"], {"delivery_issue": True})
        return "ignored"
    if not customer:
        return flag(inbound, conversation, unverified_reason, "unknown_sender", rules.holding_draft("unknown_sender", None, org))
    try:
        return decide(mail, inbound, conversation, customer, customers, org)
    except Exception as error:
        log.exception("Processing failed")
        return flag(inbound, conversation, f"Processing error ({type(error).__name__}), please handle manually", "other",
                    rules.holding_draft("other", customer, org))


def check_inbox():
    if not email_client.configured():
        raise AppError("Email is not configured: set ORG_EMAIL and ORG_EMAIL_PASSWORD in .env", 503)
    if not inbox_lock.acquire(blocking=False):
        raise AppError("An inbox check is already running", 409)
    try:
        repo.ensure_indexes()
        mails = email_client.fetch_unseen()
        customers, org = customer_repo.list_all(), organization_repo.get()
        summary = {"fetched": len(mails), "auto_answered": 0, "needs_attention": 0, "ignored": 0, "duplicate": 0, "errors": 0}
        seen = []
        for mail in mails:
            try:
                outcome = process_mail(mail, customers, org)
            except Exception:
                log.exception("Could not process an email")
                summary["errors"] += 1
                continue
            summary[outcome] += 1
            seen.append(mail["uid"])
        email_client.mark_seen(seen)
        return summary
    finally:
        inbox_lock.release()


def list_conversations():
    return repo.list_conversations()


def get_conversation(conversation_id):
    conversation = repo.get_conversation(conversation_id)
    if not conversation:
        raise AppError("Conversation not found", 404)
    return {**conversation, "messages": repo.messages_in(conversation_id)}


def list_attention():
    items = []
    for message in repo.attention_items():
        conversation = repo.get_conversation(message["conversation_id"]) or {}
        items.append({
            **message, "customer_name": conversation.get("customer_name"), "conversation_kind": conversation.get("kind"),
        })
    return items


def open_item(item_id):
    item = repo.get_message(item_id)
    if not item or item.get("attention", {}).get("status") != "open":
        raise AppError("This item is not waiting for attention", 404)
    return item


def send_attention_reply(item_id, body, confirm=False):
    item = open_item(item_id)
    conversation = repo.get_conversation(item["conversation_id"])
    customers = customer_repo.list_all()
    customer = next((c for c in customers if c["customer_id"] == conversation.get("customer_id")), None)
    if customer and item.get("sender_verified"):
        problems = rules.validate_draft(body, customer, organization_repo.get(), rules.open_invoices(customer["customer_id"]), customers)
        if problems and not confirm:
            raise AppError("This reply has figures that do not match the records: " + "; ".join(problems) + ". Send again with confirm to send it anyway.", 409)
    message_id = email_client.send_email(
        item["from_email"], reply_subject(item["subject"]), body, in_reply_to=item["message_id"],
        references=" ".join([*item.get("references", []), item["message_id"]])[-900:],
    )
    repo.add_message(new_message(
        conversation, direction="outbound", kind="manual_reply", message_id=message_id, from_email=settings.org_email,
        to_email=item["from_email"], subject=reply_subject(item["subject"]), body=body,
        in_reply_to=item["message_id"], status="sent",
    ))
    repo.update_message(item_id, {"attention.status": "resolved", "attention.resolution": "replied", "attention.resolved_at": now_iso()})
    refresh_attention_flag(conversation["conversation_id"])
    return {"status": "sent", "to": item["from_email"]}


def dismiss_attention(item_id):
    item = open_item(item_id)
    repo.update_message(item_id, {"attention.status": "resolved", "attention.resolution": "dismissed", "attention.resolved_at": now_iso()})
    refresh_attention_flag(item["conversation_id"])
    return {"status": "dismissed"}


def safe(job):
    def run():
        try:
            job()
        except AppError as error:
            log.info("Scheduled job skipped: %s", error.message)
        except Exception:
            log.exception("Scheduled job failed")
    return run


def start_scheduler():
    scheduler = BackgroundScheduler()
    if email_client.configured() and settings.imap_poll_seconds > 0:
        scheduler.add_job(safe(check_inbox), "interval", seconds=settings.imap_poll_seconds, max_instances=1, coalesce=True)
    if settings.auto_reminders and email_client.ready_to_send():
        scheduler.add_job(safe(send_reminders), "interval", hours=settings.reminder_interval_hours, max_instances=1, coalesce=True)
    if not scheduler.get_jobs():
        return None
    scheduler.start()
    return scheduler