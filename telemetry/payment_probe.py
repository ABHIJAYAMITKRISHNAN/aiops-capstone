"""Synthetic end-to-end payment probe.

Two of the four controlled faults (AUTH_KEY_ERROR and NOTIFICATION_LATENCY) only manifest when a
real request flows through the system - passive /actuator/health and /actuator/prometheus polling
alone never observes them. This probe performs a real login + payment on a schedule so the
telemetry stream also captures actual business-flow symptoms (HTTP status, duration,
notificationStatus) during fault windows, not just infrastructure metrics.

Design note - token caching is deliberate, not an oversight: a real client logs in once and
reuses that token for a while. If this probe fetched a *fresh* token on every call, it would
never observe the AUTH_KEY_ERROR fault, because a token minted *after* the key was swapped always
validates against whatever key is currently active. Caching the token (and only refreshing it
when it's actually expired) means a token obtained before the fault keeps being reused while the
fault is active, so it genuinely starts failing - exactly like a real logged-in user would
experience it.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from . import config
from .util import new_correlation_id, now_iso


def _service_url(name: str) -> str:
    return next(s.base_url for s in config.SERVICES if s.name == name)


class PaymentProbe:
    def __init__(self):
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _ensure_token(self, correlation_id: str) -> Optional[str]:
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token
        try:
            resp = requests.post(
                f"{_service_url('auth-service')}/api/auth/login",
                json={"username": config.PROBE_USERNAME, "password": config.PROBE_PASSWORD},
                headers={"X-Correlation-Id": correlation_id},
                timeout=config.HTTP_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            body = resp.json()
            self._token = body["token"]
            # Refresh a little before actual expiry so we don't probe with an expired token.
            expires_in_ms = body.get("expiresInMs", 3_600_000)
            self._token_expires_at = time.monotonic() + max(5.0, (expires_in_ms / 1000.0) - 30.0)
            return self._token
        except Exception:  # noqa: BLE001 - login failure is a valid, recordable probe outcome
            self._token = None
            return None

    def force_new_token(self) -> None:
        """Discard the cached token so the next probe logs in again (useful after a
        reset-auth-key call, so probes go back to using a token minted under the restored key)."""
        self._token = None
        self._token_expires_at = 0.0

    def probe(self) -> dict:
        correlation_id = new_correlation_id()
        started = time.monotonic()
        record = {
            "timestamp": now_iso(),
            "type": "payment_probe",
            "correlation_id": correlation_id,
        }

        token = self._ensure_token(correlation_id)
        if token is None:
            record.update(
                success=False,
                stage="login",
                error="login failed or auth-service unreachable",
                duration_ms=round((time.monotonic() - started) * 1000, 1),
            )
            return record

        try:
            resp = requests.post(
                f"{_service_url('payment-service')}/api/payments",
                json={
                    "accountId": config.PROBE_ACCOUNT_ID,
                    "currency": config.PROBE_CURRENCY,
                    "amount": config.PROBE_AMOUNT,
                },
                headers={"Authorization": f"Bearer {token}", "X-Correlation-Id": correlation_id},
                # Payment can legitimately take longer than the usual HTTP timeout while the
                # notification-latency fault is active (payment-service's own timeout is ~5s).
                timeout=config.HTTP_TIMEOUT_SECONDS * 3,
            )
            duration_ms = round((time.monotonic() - started) * 1000, 1)
            body: dict = {}
            try:
                body = resp.json()
            except ValueError:
                pass
            record.update(
                success=resp.status_code == 200,
                stage="payment",
                http_status=resp.status_code,
                duration_ms=duration_ms,
                payment_status=body.get("status"),
                notification_status=body.get("notificationStatus"),
                ledger_transaction_id=body.get("ledgerTransactionId"),
                error=body.get("error"),
            )
        except requests.exceptions.RequestException as exc:
            record.update(
                success=False,
                stage="payment",
                error=str(exc),
                duration_ms=round((time.monotonic() - started) * 1000, 1),
            )
        return record
