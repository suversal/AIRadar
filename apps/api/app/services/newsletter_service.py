"""Double-opt-in weekly newsletter and idempotent SMTP delivery.

The database is the source of truth.  A scheduler may call
``dispatch_latest_weekly`` repeatedly or from more than one process: the
unique delivery ledger and stale-claim recovery prevent duplicate sends while
still allowing a crashed SMTP attempt to be retried.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import os
import re
import secrets
import smtplib
import ssl
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Mapping, Protocol
from urllib.parse import quote

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError

from app.db.models import NewsletterDeliveryModel, NewsletterSubscriberModel


CONFIRMATION_TTL = timedelta(hours=48)
CONFIRMATION_RESEND_COOLDOWN = timedelta(minutes=10)
CONFIRMATION_GLOBAL_WINDOW = timedelta(hours=1)
CONFIRMATION_GLOBAL_MAX = 100
DELIVERY_STALE_AFTER = timedelta(minutes=30)
DELIVERY_MAX_ATTEMPTS = 5

EMAIL_RE = re.compile(
    r"^(?=.{3,320}$)[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)


class NewsletterValidationError(ValueError):
    pass


class NewsletterConfigurationError(RuntimeError):
    pass


class NewsletterDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class NewsletterMessage:
    to_email: str
    subject: str
    text: str
    html: str
    headers: Mapping[str, str] = field(default_factory=dict)


class NewsletterMailer(Protocol):
    def send(self, message: NewsletterMessage) -> str | None: ...


@dataclass(frozen=True)
class SMTPNewsletterMailer:
    host: str
    port: int
    from_email: str
    from_name: str = "AI·RADAR"
    username: str | None = None
    password: str | None = None
    use_starttls: bool = True
    use_ssl: bool = False
    timeout_seconds: int = 20

    @classmethod
    def from_env(cls) -> "SMTPNewsletterMailer":
        host = (os.getenv("NEWSLETTER_SMTP_HOST") or "").strip()
        from_email = (os.getenv("NEWSLETTER_FROM_EMAIL") or "").strip()
        if not host or not from_email:
            raise NewsletterConfigurationError(
                "set NEWSLETTER_SMTP_HOST and NEWSLETTER_FROM_EMAIL"
            )
        use_ssl = _env_bool("NEWSLETTER_SMTP_SSL", False)
        default_port = 465 if use_ssl else 587
        return cls(
            host=host,
            port=_env_int("NEWSLETTER_SMTP_PORT", default_port, minimum=1, maximum=65535),
            from_email=from_email,
            from_name=(os.getenv("NEWSLETTER_FROM_NAME") or "AI·RADAR").strip(),
            username=(os.getenv("NEWSLETTER_SMTP_USERNAME") or "").strip() or None,
            password=os.getenv("NEWSLETTER_SMTP_PASSWORD") or None,
            use_starttls=_env_bool("NEWSLETTER_SMTP_STARTTLS", not use_ssl),
            use_ssl=use_ssl,
            timeout_seconds=_env_int(
                "NEWSLETTER_SMTP_TIMEOUT_SECONDS", 20, minimum=3, maximum=120
            ),
        )

    def send(self, message: NewsletterMessage) -> str | None:
        email = EmailMessage()
        email["From"] = formataddr((self.from_name, self.from_email))
        email["To"] = message.to_email
        email["Subject"] = message.subject
        for key, value in message.headers.items():
            email[key] = value
        email.set_content(message.text)
        email.add_alternative(message.html, subtype="html")

        smtp_class = smtplib.SMTP_SSL if self.use_ssl else smtplib.SMTP
        context = ssl.create_default_context()
        kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "timeout": self.timeout_seconds,
        }
        if self.use_ssl:
            kwargs["context"] = context
        with smtp_class(**kwargs) as client:
            if self.use_starttls and not self.use_ssl:
                client.starttls(context=context)
            if self.username:
                if self.password is None:
                    raise NewsletterConfigurationError(
                        "NEWSLETTER_SMTP_PASSWORD is required when username is set"
                    )
                client.login(self.username, self.password)
            refused = client.send_message(email)
        if refused:
            raise NewsletterDeliveryError("SMTP server refused one or more recipients")
        message_id = email.get("Message-ID")
        return str(message_id) if message_id else None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def newsletter_enabled() -> bool:
    return _env_bool("NEWSLETTER_ENABLED", False)


def newsletter_site_url() -> str:
    return (os.getenv("NEWSLETTER_SITE_URL") or "https://radar.suversal.com").rstrip("/")


def newsletter_token_secret() -> str:
    secret = (os.getenv("NEWSLETTER_TOKEN_SECRET") or os.getenv("JWT_SECRET") or "").strip()
    if not secret or secret in {"dev-only-change-me", "change-me"}:
        raise NewsletterConfigurationError(
            "set NEWSLETTER_TOKEN_SECRET (or a non-default JWT_SECRET)"
        )
    return secret


def normalize_email(value: str) -> str:
    normalized = (value or "").strip().lower()
    if not EMAIL_RE.fullmatch(normalized):
        raise NewsletterValidationError("请输入有效的邮箱地址。")
    return normalized


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_confirmation_token() -> str:
    return secrets.token_urlsafe(32)


def unsubscribe_token_for(subscriber_id: str, secret: str) -> str:
    signature = hmac.new(
        secret.encode("utf-8"),
        subscriber_id.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{subscriber_id}.{signature}"


def request_subscription(
    repository: Any,
    mailer: NewsletterMailer,
    *,
    email: str,
    source: str = "weekly_page",
    now: datetime | None = None,
    site_url: str | None = None,
    token_secret: str | None = None,
) -> dict[str, Any]:
    """Create/refresh a pending subscription and send its confirmation mail.

    The public response deliberately does not reveal whether an address is
    already active.  Active addresses are not emailed again.
    """
    now = _aware_utc(now or datetime.now(timezone.utc))
    normalized = normalize_email(email)
    site_url = (site_url or newsletter_site_url()).rstrip("/")
    token_secret = token_secret or newsletter_token_secret()
    existing = repository.get_newsletter_subscriber_by_email(normalized)

    if existing is not None and existing.status == "active":
        return {"accepted": True, "sent": False}
    if (
        existing is not None
        and existing.confirmation_sent_at is not None
        and now - _aware_utc(existing.confirmation_sent_at) < CONFIRMATION_RESEND_COOLDOWN
    ):
        return {"accepted": True, "sent": False}
    if (
        repository.count_newsletter_confirmations_sent_since(
            now - CONFIRMATION_GLOBAL_WINDOW
        )
        >= CONFIRMATION_GLOBAL_MAX
    ):
        return {"accepted": True, "sent": False}

    raw_confirmation = _new_confirmation_token()
    confirmation_hash = token_hash(raw_confirmation)
    if existing is None:
        subscriber_id = uuid.uuid4().hex
        raw_unsubscribe = unsubscribe_token_for(subscriber_id, token_secret)
        subscriber = NewsletterSubscriberModel(
            id=subscriber_id,
            email=normalized,
            status="pending",
            confirmation_token_hash=confirmation_hash,
            unsubscribe_token_hash=token_hash(raw_unsubscribe),
            confirmation_expires_at=now + CONFIRMATION_TTL,
            source=(source or "weekly_page")[:80],
        )
        repository.session.add(subscriber)
    else:
        subscriber = existing
        raw_unsubscribe = unsubscribe_token_for(subscriber.id, token_secret)
        subscriber.status = "pending"
        subscriber.confirmation_token_hash = confirmation_hash
        subscriber.unsubscribe_token_hash = token_hash(raw_unsubscribe)
        subscriber.confirmation_expires_at = now + CONFIRMATION_TTL
        subscriber.confirmed_at = None
        subscriber.unsubscribed_at = None
        subscriber.source = (source or "weekly_page")[:80]

    try:
        # Claim the normalized address before opening SMTP.  Concurrent
        # submissions for the same new address then produce at most one mail.
        repository.session.flush()
    except IntegrityError:
        repository.session.rollback()
        return {"accepted": True, "sent": False}

    message = render_confirmation_message(
        to_email=normalized,
        confirmation_url=(
            f"{site_url}/newsletter/confirm?token={quote(raw_confirmation, safe='')}"
        ),
    )
    try:
        mailer.send(message)
    except Exception as exc:
        repository.session.rollback()
        raise NewsletterDeliveryError(_safe_delivery_error(exc)) from exc
    subscriber.confirmation_sent_at = now
    repository.session.commit()
    return {"accepted": True, "sent": True}


def confirm_subscription(
    repository: Any, *, token: str, now: datetime | None = None
) -> str:
    now = _aware_utc(now or datetime.now(timezone.utc))
    if not token or len(token) > 256:
        return "invalid"
    subscriber = repository.get_newsletter_subscriber_by_confirmation_hash(token_hash(token))
    if subscriber is None:
        return "invalid"
    if subscriber.status == "active":
        return "already_active"
    if now > _aware_utc(subscriber.confirmation_expires_at):
        return "expired"
    subscriber.status = "active"
    subscriber.confirmed_at = now
    subscriber.unsubscribed_at = None
    repository.session.commit()
    return "confirmed"


def unsubscribe(
    repository: Any, *, token: str, now: datetime | None = None
) -> str:
    now = _aware_utc(now or datetime.now(timezone.utc))
    if not token or len(token) > 256:
        return "invalid"
    subscriber = repository.get_newsletter_subscriber_by_unsubscribe_hash(token_hash(token))
    if subscriber is None:
        return "invalid"
    if subscriber.status == "unsubscribed":
        return "already_unsubscribed"
    subscriber.status = "unsubscribed"
    subscriber.unsubscribed_at = now
    repository.session.commit()
    return "unsubscribed"


def dispatch_latest_weekly(
    repository: Any,
    mailer: NewsletterMailer,
    *,
    now: datetime | None = None,
    site_url: str | None = None,
    token_secret: str | None = None,
    include_late_subscribers: bool = False,
) -> dict[str, Any]:
    now = _aware_utc(now or datetime.now(timezone.utc))
    site_url = (site_url or newsletter_site_url()).rstrip("/")
    token_secret = token_secret or newsletter_token_secret()
    report = repository.latest_finalized_weekly_report()
    if report is None:
        return {"period_key": None, "sent": 0, "failed": 0, "skipped": 0}

    finalized_at = _aware_utc(datetime.fromisoformat(report["finalized_at"]))
    subscribers = repository.list_active_newsletter_subscribers(
        confirmed_before=None if include_late_subscribers else finalized_at
    )
    hydrated = _hydrate_weekly_report(repository, report)
    result = {
        "period_key": report["period_key"],
        "sent": 0,
        "failed": 0,
        "skipped": 0,
    }
    for subscriber in subscribers:
        delivery = _claim_delivery(
            repository,
            subscriber_id=subscriber.id,
            period_key=report["period_key"],
            now=now,
        )
        if delivery is None:
            result["skipped"] += 1
            continue
        raw_unsubscribe = unsubscribe_token_for(subscriber.id, token_secret)
        unsubscribe_url = (
            f"{site_url}/newsletter/unsubscribe?token={quote(raw_unsubscribe, safe='')}"
        )
        one_click_url = (
            f"{site_url}/api/newsletter/unsubscribe?token={quote(raw_unsubscribe, safe='')}"
        )
        message = render_weekly_message(
            to_email=subscriber.email,
            report=hydrated,
            site_url=site_url,
            unsubscribe_url=unsubscribe_url,
            one_click_url=one_click_url,
        )
        try:
            message_id = mailer.send(message)
        except Exception as exc:
            delivery.status = "failed"
            delivery.last_error = _safe_delivery_error(exc)
            repository.session.commit()
            result["failed"] += 1
            continue
        delivery.status = "sent"
        delivery.sent_at = now
        delivery.provider_message_id = (message_id or "")[:255] or None
        delivery.last_error = None
        repository.session.commit()
        result["sent"] += 1
    return result


def _claim_delivery(
    repository: Any, *, subscriber_id: str, period_key: str, now: datetime
) -> NewsletterDeliveryModel | None:
    delivery = repository.get_newsletter_delivery(
        subscriber_id=subscriber_id, period_key=period_key
    )
    if delivery is None:
        delivery = NewsletterDeliveryModel(
            subscriber_id=subscriber_id,
            period_key=period_key,
            status="sending",
            attempt_count=1,
            claimed_at=now,
        )
        repository.session.add(delivery)
        try:
            repository.session.commit()
        except IntegrityError:
            repository.session.rollback()
            return None
        return delivery
    stale_before = now - DELIVERY_STALE_AFTER
    claim = repository.session.execute(
        update(NewsletterDeliveryModel)
        .where(
            NewsletterDeliveryModel.id == delivery.id,
            NewsletterDeliveryModel.status != "sent",
            NewsletterDeliveryModel.attempt_count < DELIVERY_MAX_ATTEMPTS,
            or_(
                NewsletterDeliveryModel.status != "sending",
                NewsletterDeliveryModel.claimed_at.is_(None),
                NewsletterDeliveryModel.claimed_at <= stale_before,
            ),
        )
        .values(
            status="sending",
            attempt_count=NewsletterDeliveryModel.attempt_count + 1,
            claimed_at=now,
            last_error=None,
        )
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        repository.session.rollback()
        return None
    repository.session.commit()
    repository.session.expire_all()
    return repository.session.get(NewsletterDeliveryModel, delivery.id)


def _hydrate_weekly_report(repository: Any, report: dict[str, Any]) -> dict[str, Any]:
    entries = list(report.get("entries") or [])
    event_ids = [str(entry.get("event_id")) for entry in entries if entry.get("event_id")]
    items = repository.get_event_items_by_ids(event_ids) if event_ids else []
    days_by_id = {
        str(entry.get("event_id")): entry.get("days_covered")
        for entry in entries
        if entry.get("event_id")
    }
    for item in items:
        days = days_by_id.get(str(item.get("event_id")))
        if days:
            item["days_covered"] = days
    return {**report, "items": items}


def render_confirmation_message(*, to_email: str, confirmation_url: str) -> NewsletterMessage:
    escaped_url = html.escape(confirmation_url, quote=True)
    text = (
        "确认订阅 AI·RADAR 周报\n\n"
        "点击下面的链接并在页面中确认。链接 48 小时内有效：\n"
        f"{confirmation_url}\n\n"
        "如果这不是你的操作，请忽略这封邮件。"
    )
    body = f"""<!doctype html>
<html lang="zh-CN"><body style="margin:0;background:#f4f4ef;color:#17221d;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f4ef;padding:32px 12px;"><tr><td align="center">
<table role="presentation" width="600" cellspacing="0" cellpadding="0" style="max-width:600px;width:100%;background:#fffef8;border:1px solid #cbd2cc;">
<tr><td style="padding:36px 40px 18px;font-family:Arial,'PingFang SC',sans-serif;">
<div style="font-size:13px;letter-spacing:2px;color:#426b57;font-weight:700;">AI·RADAR WEEKLY</div>
<h1 style="margin:16px 0 10px;font-size:28px;line-height:1.3;color:#17221d;">确认订阅周报</h1>
<p style="margin:0;color:#536159;font-size:15px;line-height:1.8;">每周一封，只发送已经封版的 AI 情报周报。</p>
</td></tr>
<tr><td style="padding:18px 40px 36px;font-family:Arial,'PingFang SC',sans-serif;">
<a href="{escaped_url}" style="display:inline-block;background:#315c48;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:13px 22px;border-radius:4px;">确认订阅</a>
<p style="margin:22px 0 0;color:#7b857f;font-size:12px;line-height:1.7;">链接 48 小时内有效。如果这不是你的操作，忽略即可，不会收到周报。</p>
</td></tr>
</table></td></tr></table></body></html>"""
    return NewsletterMessage(
        to_email=to_email,
        subject="请确认订阅 AI·RADAR 周报",
        text=text,
        html=body,
    )


def render_weekly_message(
    *,
    to_email: str,
    report: dict[str, Any],
    site_url: str,
    unsubscribe_url: str,
    one_click_url: str,
) -> NewsletterMessage:
    period_key = str(report.get("period_key") or "")
    range_label = f"{report.get('range_start', '')} — {report.get('range_end', '')}"
    title = str(report.get("mainline_title") or "本周 AI 情报")
    mainline = str(report.get("mainline_body") or "本期周报已封版。")
    report_url = f"{site_url}/weekly/{quote(period_key, safe='-W')}"
    unsubscribe_escaped = html.escape(unsubscribe_url, quote=True)
    report_url_escaped = html.escape(report_url, quote=True)
    grouped = _group_weekly_items(list(report.get("items") or []))

    section_html: list[str] = []
    text_sections: list[str] = []
    for index, (label, items) in enumerate(grouped[:5], start=1):
        cards: list[str] = []
        text_items: list[str] = []
        for item in items[:3]:
            event_url = f"{site_url}/event/{quote(str(item.get('event_id') or ''), safe='')}"
            summary = str(item.get("one_line_summary") or item.get("summary") or "")
            source_count = int(item.get("source_count") or 1)
            meta = f"{source_count} 家报道" if source_count > 1 else "单一信源"
            cards.append(
                "<tr><td style=\"padding:15px 0;border-bottom:1px solid #dfe3df;\">"
                f"<a href=\"{html.escape(event_url, quote=True)}\" style=\"color:#17221d;text-decoration:none;font-size:17px;line-height:1.55;font-weight:700;\">{html.escape(str(item.get('title') or ''))}</a>"
                f"<p style=\"margin:6px 0 0;color:#5d6962;font-size:14px;line-height:1.7;\">{html.escape(summary)}</p>"
                f"<p style=\"margin:7px 0 0;color:#678070;font-size:12px;\">{html.escape(meta)}</p>"
                "</td></tr>"
            )
            text_items.append(f"- {item.get('title', '')}\n  {summary}\n  {event_url}")
        section_html.append(
            "<tr><td style=\"padding:28px 40px 0;font-family:Arial,'PingFang SC',sans-serif;\">"
            f"<div style=\"font-size:12px;color:#4f755f;letter-spacing:1.5px;font-weight:700;\">{index:02d} / {html.escape(label)}</div>"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\">"
            f"{''.join(cards)}</table></td></tr>"
        )
        text_sections.append(f"{index:02d} / {label}\n" + "\n".join(text_items))

    subject = f"AI·RADAR 周报｜{title}"
    text = (
        f"AI·RADAR 周报 {period_key}\n{range_label}\n\n"
        f"本周主线：{title}\n{mainline}\n\n"
        + "\n\n".join(text_sections)
        + f"\n\n阅读完整周报：{report_url}\n取消订阅：{unsubscribe_url}"
    )
    body = f"""<!doctype html>
<html lang="zh-CN"><body style="margin:0;background:#f4f4ef;color:#17221d;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{html.escape(mainline[:100])}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f4ef;padding:20px 8px;"><tr><td align="center">
<table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%;background:#fffef8;border:1px solid #bdc7c0;">
<tr><td style="padding:34px 40px 26px;font-family:Arial,'PingFang SC',sans-serif;border-bottom:1px solid #d8ddd9;">
<div style="font-size:13px;letter-spacing:2px;color:#416b56;font-weight:700;">AI·RADAR WEEKLY</div>
<h1 style="margin:14px 0 8px;font-size:30px;line-height:1.3;color:#17221d;">一周 AI 信号</h1>
<div style="font-size:13px;color:#77827c;">{html.escape(period_key)} · {html.escape(range_label)}</div>
</td></tr>
<tr><td style="padding:30px 40px 6px;font-family:Arial,'PingFang SC',sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#edf1ed;border-left:4px solid #4d765f;"><tr><td style="padding:24px 24px;">
<div style="font-size:11px;letter-spacing:2px;color:#4d765f;font-weight:700;">THIS WEEK IN ONE SENTENCE</div>
<h2 style="margin:12px 0 8px;font-size:23px;line-height:1.45;color:#17221d;">{html.escape(title)}</h2>
<p style="margin:0;color:#536159;font-size:15px;line-height:1.8;">{html.escape(mainline)}</p>
</td></tr></table></td></tr>
{''.join(section_html)}
<tr><td align="center" style="padding:34px 40px 38px;font-family:Arial,'PingFang SC',sans-serif;">
<a href="{report_url_escaped}" style="display:inline-block;background:#315c48;color:#ffffff;text-decoration:none;font-size:14px;font-weight:700;padding:13px 22px;border-radius:4px;">阅读完整周报</a>
</td></tr>
<tr><td style="padding:25px 40px;background:#e9eee9;border-top:1px solid #c9d2cb;font-family:Arial,'PingFang SC',sans-serif;">
<div style="font-size:15px;font-weight:700;color:#263a30;">AI·RADAR</div>
<p style="margin:5px 0 0;color:#657169;font-size:12px;line-height:1.7;">不追逐每一条消息，只标记真正的信号。</p>
<p style="margin:12px 0 0;color:#7a857f;font-size:11px;line-height:1.7;">你收到这封邮件，是因为你确认订阅了 AI·RADAR 周报。<a href="{unsubscribe_escaped}" style="color:#526d5e;">取消订阅</a></p>
</td></tr>
</table></td></tr></table></body></html>"""
    return NewsletterMessage(
        to_email=to_email,
        subject=subject[:180],
        text=text,
        html=body,
        headers={
            "List-Unsubscribe": f"<{one_click_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )


def _group_weekly_items(items: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        label = str(
            item.get("focus_category_label")
            or item.get("category_label")
            or item.get("category")
            or "其他"
        )
        groups.setdefault(label, []).append(item)
    return list(groups.items())


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _safe_delivery_error(exc: Exception) -> str:
    # SMTP errors may include recipient addresses; keep the durable ledger
    # useful without persisting credentials, server banners, or full payloads.
    return exc.__class__.__name__[:120]
