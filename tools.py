"""Actions the AI assistant is allowed to take. Each tool validates its input,
because the model can make mistakes and customers can try to trick it."""
import re

import store


def normalize_phone(raw):
    """Return a 10-digit Indian mobile number, or None if it does not look valid."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if re.fullmatch(r"[6-9]\d{9}", digits) else None


def notify_owner(message: str):
    """Phase 1: print to the console. Later: send an email, Telegram or WhatsApp alert."""
    print(f"\n[OWNER ALERT] {message}\n")


def make_tools(business_id: str, session_id: str):
    """Build the tools for one chat. Python functions with type hints and
    docstrings are turned into tool definitions by the Gemini SDK."""

    def save_lead(name: str, phone: str, interest: str, consent_given: bool,
                  preferred_time: str = "", kind: str = "enquiry") -> dict:
        """Save a customer's contact details so the business team can call them back.
        Call this ONLY after the customer has agreed to share their name and phone
        number with the business.

        Args:
            name: The customer's name.
            phone: The customer's 10-digit Indian mobile number.
            interest: What they want (for example 'monthly gym membership' or 'haircut').
            consent_given: True only if the customer agreed to share their details
                with the business so the team can contact them.
            preferred_time: When they would like to visit or be called, if they said.
            kind: 'enquiry' for a general lead, or 'visit_request' if they asked to
                visit, take a trial, or book a slot.
        """
        if consent_given is not True:
            return {"saved": False,
                    "error": "Customer has not agreed to share their details. "
                             "Ask for permission first."}
        clean = normalize_phone(phone)
        if not clean:
            return {"saved": False,
                    "error": "That phone number is not a valid 10-digit Indian "
                             "mobile number. Ask the customer to re-enter it."}
        if not (name or "").strip():
            return {"saved": False, "error": "Name is missing. Ask for it."}
        kind = kind if kind in ("enquiry", "visit_request") else "enquiry"

        lead_id, dup = store.add_lead(business_id, session_id, kind, name.strip(),
                                      clean, (interest or "").strip(),
                                      (preferred_time or "").strip(), True)
        if not dup:
            label = "VISIT REQUEST" if kind == "visit_request" else "NEW LEAD"
            notify_owner(f"{label} #{lead_id}: {name.strip()} | {clean} | "
                         f"{interest} | preferred: {preferred_time or 'not given'}")
        return {"saved": True, "lead_id": lead_id,
                "note": "The team will confirm. Do not promise a confirmed booking."}

    def handoff_to_human(reason: str, customer_message: str) -> dict:
        """Ask a human team member to take over this conversation. Use this when you
        do not know the answer, the customer is upset or has a complaint or refund
        issue, they ask for medical advice, or they ask to speak to a person.

        Args:
            reason: A short reason for the hand-off.
            customer_message: The customer's last message, so the team has context.
        """
        hid = store.add_handoff(business_id, session_id, reason, customer_message)
        notify_owner(f"HAND-OFF #{hid}: {reason} | customer said: {customer_message}")
        return {"handoff_requested": True,
                "note": "Tell the customer a team member will get back to them."}

    return [save_lead, handoff_to_human]
