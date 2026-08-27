import responses

from telemetry.payment_probe import PaymentProbe

LOGIN_URL = "http://localhost:8081/api/auth/login"
PAYMENT_URL = "http://localhost:8082/api/payments"


def _mock_login(token="tok-1", expires_in_ms=3_600_000):
    responses.add(responses.POST, LOGIN_URL, json={"token": token, "tokenType": "Bearer", "expiresInMs": expires_in_ms}, status=200)


def _mock_payment(status=200, body=None):
    responses.add(responses.POST, PAYMENT_URL, json=body or {
        "status": "ACCEPTED", "message": "ok", "authenticatedUser": "alice",
        "ledgerTransactionId": "tx-1", "notificationStatus": "SENT",
    }, status=status)


class TestPaymentProbeTokenCaching:
    @responses.activate
    def test_reuses_cached_token_across_multiple_probes(self):
        _mock_login()
        _mock_payment()
        _mock_payment()

        probe = PaymentProbe()
        r1 = probe.probe()
        r2 = probe.probe()

        login_calls = [c for c in responses.calls if c.request.url == LOGIN_URL]
        assert len(login_calls) == 1  # only the first probe logged in
        assert r1["success"] is True
        assert r2["success"] is True

    @responses.activate
    def test_force_new_token_triggers_a_fresh_login_on_next_probe(self):
        _mock_login(token="tok-1")
        _mock_payment()
        _mock_login(token="tok-2")
        _mock_payment()

        probe = PaymentProbe()
        probe.probe()
        probe.force_new_token()
        probe.probe()

        login_calls = [c for c in responses.calls if c.request.url == LOGIN_URL]
        assert len(login_calls) == 2

    @responses.activate
    def test_login_failure_is_recorded_without_raising(self):
        responses.add(responses.POST, LOGIN_URL, status=401)

        probe = PaymentProbe()
        record = probe.probe()

        assert record["success"] is False
        assert record["stage"] == "login"

    @responses.activate
    def test_payment_failure_is_recorded_with_status_and_duration(self):
        _mock_login()
        responses.add(responses.POST, PAYMENT_URL, json={"error": "Insufficient funds in account: acct-42"}, status=409)

        probe = PaymentProbe()
        record = probe.probe()

        assert record["success"] is False
        assert record["stage"] == "payment"
        assert record["http_status"] == 409
        assert record["duration_ms"] >= 0
