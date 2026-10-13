from __future__ import annotations

from dataclasses import dataclass, field

import logging

from django.utils import timezone

from ..conf import setting
from ..models import AnomalyEvent, Lockout, SecurityPolicy, SessionEvent
from . import detector, features, geo, networks, sessions

logger = logging.getLogger("dbs")

OK = "ok"
WARN = "warn"
BLOCK = "block"

ACTIONS = {OK: "continue", WARN: "reauth", BLOCK: "logout"}


@dataclass
class Verdict:
    level: str = OK
    score: float = 0.0
    reasons: list = field(default_factory=list)

    @property
    def action(self) -> str:
        return ACTIONS[self.level]


def enforcement_enabled() -> bool:
    return bool(setting("DBS_ANOMALY_ENFORCE", True))


MINIMUM_PREFIX = networks.MINIMUM_PREFIX


def _within(address: str, raw: str) -> bool:
    expected = networks.parse_networks(raw)
    return not expected or networks.contains(expected, address)


def is_trusted(address: str, policy) -> bool:
    trusted = networks.parse_networks(setting("DBS_TRUSTED_NETWORKS", ()) or ())
    trusted += networks.parse_networks(policy.trusted_networks or "")
    return networks.contains(trusted, address)


def is_locked_out(user) -> bool:
    return Lockout.objects.filter(user=user).exists()


def evaluate(request, action="view", location=None) -> Verdict:
    user = request.user
    policy = SecurityPolicy.load()
    location = geo.clean(location)
    observation, address, prefix, agent = features.observe_request(
        user, request, action, location
    )
    values = features.build(observation)

    model_score = detector.get_detector().score(user, values)
    rules, reasons = detector.rule_score(values)
    if not address:
        reasons.append("the client address could not be determined")
    if policy.expected_networks and not _within(address, policy.expected_networks):
        rules = min(1.0, rules + 0.2)
        reasons.append("outside the networks this project expects logins from")
    score = max(model_score, rules)

    trusted = is_trusted(address, policy)
    learning = _still_learning(user, policy)
    level = _level(score, policy, trusted, learning)

    _record(user, request, values, address, prefix, agent, location, score, level)
    return Verdict(level=level, score=round(score, 4), reasons=reasons)


def _still_learning(user, policy) -> bool:
    if not policy.learning_logins:
        return False
    seen = (
        SessionEvent.objects.filter(user=user)
        .values("session_key_hash")
        .distinct()
        .count()
    )
    return seen < policy.learning_logins


def _level(score, policy, trusted, learning) -> str:
    if trusted or learning:
        return OK
    if not enforcement_enabled():
        return OK if score < policy.warn_threshold else WARN
    if score >= policy.logout_threshold:
        return BLOCK
    if score >= policy.warn_threshold:
        return WARN
    return OK


def _record(user, request, values, address, prefix, agent, location, score, level):
    SessionEvent.objects.create(
        user=user,
        session_key_hash=features.digest(request.session.session_key or ""),
        kind="request",
        remote_addr=address,
        ip_prefix=prefix,
        ua_hash=agent,
        latitude=location["latitude"] if location else None,
        longitude=location["longitude"] if location else None,
        accuracy_m=location["accuracy"] if location else None,
        features=values,
        score=score,
        verdict=level,
    )


def apply(verdict, request) -> None:
    user = request.user
    if verdict.level == BLOCK:
        AnomalyEvent.objects.create(
            user=user,
            score=verdict.score,
            reasons=verdict.reasons,
            action_taken="logout",
            remote_addr=features.client_address(request),
        )
        Lockout.objects.get_or_create(
            user=user, defaults={"reason": "; ".join(verdict.reasons)}
        )
        sessions.terminate(user)
        notify(user, verdict)
    elif verdict.level == WARN:
        AnomalyEvent.objects.create(
            user=user,
            score=verdict.score,
            reasons=verdict.reasons,
            action_taken="warn",
            remote_addr=features.client_address(request),
        )
        sessions.mark_for_reauthentication(request)


def notify(user, verdict) -> None:
    policy = SecurityPolicy.load()
    recipients = [
        line.strip()
        for line in (policy.notify_emails or "").replace(",", "\n").split("\n")
        if line.strip()
    ]
    if not recipients:
        return
    from django.core.mail import send_mail

    try:
        _send(send_mail, user, verdict, recipients)
    except Exception:
        logger.warning("could not send the DBS anomaly notification", exc_info=True)


def _send(send_mail, user, verdict, recipients):
    send_mail(
        subject="DBS ended an admin session",
        message=(
            f"DBS ended {user.get_username()}'s admin session at "
            f"{timezone.now():%Y-%m-%d %H:%M %Z}.\n\n"
            + "\n".join(f"- {reason}" for reason in verdict.reasons)
        ),
        from_email=None,
        recipient_list=recipients,
        fail_silently=True,
    )
