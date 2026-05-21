from email.message import EmailMessage
import html
import re
import smtplib


DEFAULT_ALERT_SUBJECT = "Warehouse alert: {alert_title}"
DEFAULT_ALERT_BODY = """{alert_title}

{alert_details}

Job: {job_name}
Job Number: {job_number}
Client: {client}
Owner: {owner}
Returned At: {returned_at}
"""


def parse_recipients(value):
    if isinstance(value, str):
        parts = re.split(r"[\n,;]+", value)
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = []
    return [str(item).strip() for item in parts if str(item).strip()]


def email_settings(settings):
    return (settings.get("alerts", {}) or {}).get("email", {}) or {}


def format_template(template, context):
    safe_context = {str(key): str(value or "") for key, value in (context or {}).items()}

    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + str(key) + "}"

    return str(template or "").format_map(SafeDict(safe_context))


def strip_html(html_text):
    text = re.sub(r"<br\s*/?>", "\n", str(html_text or ""), flags=re.IGNORECASE)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]*>", " ", text)
    return html.unescape(re.sub(r"[ \t\r\f\v]+", " ", text).strip())


def alert_email_enabled(settings, alert):
    alerts = settings.get("alerts", {}) or {}
    config = email_settings(settings)
    if not config.get("enabled", False):
        return False

    event_type = str((alert or {}).get("type", "")).strip()
    event_config = (alerts.get("event_types", {}) or {}).get(event_type, {}) or {}
    return bool(event_config.get("send_email", False))


def alert_email_context(alert):
    alert = alert or {}
    context = {}
    if isinstance(alert.get("email_context"), dict):
        context.update(alert.get("email_context"))
    context.setdefault("job_name", "")
    context.setdefault("job_number", "")
    context.setdefault("client", "")
    context.setdefault("owner", "")
    context.setdefault("returned_at", "")
    context.update(
        {
            "alert_type": str(alert.get("type") or ""),
            "alert_title": str(alert.get("title") or alert.get("type") or "Warehouse Alert"),
            "alert_details": strip_html(alert.get("html", "")),
        }
    )
    return context


def build_alert_message(settings, alert):
    config = email_settings(settings)
    subject_template = config.get("subject_template") or DEFAULT_ALERT_SUBJECT
    body_template = config.get("body_template") or DEFAULT_ALERT_BODY
    context = alert_email_context(alert)
    return format_template(subject_template, context), format_template(body_template, context)


def send_smtp_message(config, subject, body):
    host = str(config.get("smtp_host", "")).strip()
    if not host:
        return False, "SMTP host is required."

    security = str(config.get("smtp_security", "starttls") or "starttls").strip().lower()
    default_port = 465 if security in {"ssl", "ssl/tls", "tls"} else 587
    try:
        port = int(config.get("smtp_port") or default_port)
    except Exception:
        port = default_port

    recipients = parse_recipients(config.get("recipients", []))
    if not recipients:
        return False, "At least one recipient email address is required."

    username = str(config.get("username", "")).strip()
    password = str(config.get("password", ""))
    from_address = str(config.get("from_address", "")).strip() or username
    if not from_address:
        return False, "A from address or SMTP username is required."

    from_name = str(config.get("from_name", "")).strip()
    sender = f"{from_name} <{from_address}>" if from_name else from_address

    message = EmailMessage()
    message["Subject"] = str(subject or "Warehouse Alert")
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(str(body or ""))

    timeout = 20
    try:
        if security in {"ssl", "ssl/tls", "tls"}:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as smtp:
                if username or password:
                    smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as smtp:
                if security in {"starttls", "start_tls"}:
                    smtp.starttls()
                if username or password:
                    smtp.login(username, password)
                smtp.send_message(message)
    except Exception as error:
        return False, f"SMTP send failed: {error}"

    return True, f"Email sent to {len(recipients)} recipient(s)."


def send_alert_email(settings, alert):
    if not alert_email_enabled(settings, alert):
        return False, "Email is disabled for this alert."
    config = email_settings(settings)
    subject, body = build_alert_message(settings, alert)
    return send_smtp_message(config, subject, body)


def send_test_email(settings):
    alert = {
        "type": "test_email",
        "title": "Warehouse Dashboard test email",
        "html": "This is a test email from the Warehouse Dashboard manager.",
        "email_context": {
            "job_name": "Test Job",
            "job_number": "TEST-123",
            "client": "Test Client",
            "owner": "Warehouse Manager",
            "returned_at": "Test time",
        },
    }
    config = email_settings(settings)
    subject, body = build_alert_message(settings, alert)
    if not subject.strip():
        subject = "Warehouse Dashboard test email"
    if not body.strip():
        body = "This is a test email from the Warehouse Dashboard manager."
    return send_smtp_message(config, subject, body)
