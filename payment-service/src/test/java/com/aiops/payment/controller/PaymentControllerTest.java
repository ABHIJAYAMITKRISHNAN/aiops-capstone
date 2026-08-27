package com.aiops.payment.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.SocketPolicy;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Each fake downstream service (MockWebServer) is started once for the whole class because the
 * WebClient beans under test resolve their base-url a single time, at Spring context startup,
 * and the context is cached and reused across these test methods. Every test that triggers a
 * downstream call must drain that server's request queue afterwards so later tests don't pick up
 * a stale request via takeRequest().
 */
@SpringBootTest
@AutoConfigureMockMvc
class PaymentControllerTest {

    private static MockWebServer mockAuthService;
    private static MockWebServer mockLedgerService;
    private static MockWebServer mockNotificationService;

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @BeforeAll
    static void startMockServers() throws IOException {
        mockAuthService = new MockWebServer();
        mockAuthService.start();
        mockLedgerService = new MockWebServer();
        mockLedgerService.start();
        mockNotificationService = new MockWebServer();
        mockNotificationService.start();
    }

    @AfterAll
    static void stopMockServers() throws IOException {
        mockAuthService.shutdown();
        mockLedgerService.shutdown();
        mockNotificationService.shutdown();
    }

    @DynamicPropertySource
    static void serviceUrls(DynamicPropertyRegistry registry) {
        registry.add("app.auth-service.base-url", () -> "http://localhost:" + mockAuthService.getPort());
        registry.add("app.ledger-service.base-url", () -> "http://localhost:" + mockLedgerService.getPort());
        registry.add("app.notification-service.base-url", () -> "http://localhost:" + mockNotificationService.getPort());
    }

    private static MockResponse jsonResponse(String body) {
        return new MockResponse().setHeader("Content-Type", "application/json").setBody(body);
    }

    private void enqueueValidAuth() {
        mockAuthService.enqueue(jsonResponse("""
                {"valid": true, "username": "alice", "roles": ["USER"], "error": null}
                """));
    }

    private void enqueueSuccessfulDebit() {
        mockLedgerService.enqueue(jsonResponse("""
                {"transactionId": "tx-abc-123", "accountId": "acct-1", "type": "DEBIT",
                 "amount": 25.00, "currency": "USD", "balanceAfter": 75.00, "createdAt": "2026-01-01T00:00:00Z"}
                """));
    }

    private void enqueueSuccessfulNotification() {
        mockNotificationService.enqueue(jsonResponse("""
                {"notificationId": "notif-1", "status": "SENT", "sentAt": "2026-01-01T00:00:00Z"}
                """));
    }

    private String paymentBody() throws Exception {
        return objectMapper.writeValueAsString(new PaymentPayload("acct-1", "USD", 25.00));
    }

    @Test
    void acceptsPaymentWhenFullChainSucceeds() throws Exception {
        enqueueValidAuth();
        enqueueSuccessfulDebit();
        enqueueSuccessfulNotification();

        mockMvc.perform(post("/api/payments")
                        .header("Authorization", "Bearer some-valid-token")
                        .contentType(APPLICATION_JSON)
                        .content(paymentBody()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("ACCEPTED"))
                .andExpect(jsonPath("$.authenticatedUser").value("alice"))
                .andExpect(jsonPath("$.ledgerTransactionId").value("tx-abc-123"))
                .andExpect(jsonPath("$.notificationStatus").value("SENT"));

        drainAll();
    }

    @Test
    void rejectsPaymentWhenTokenIsInvalid() throws Exception {
        mockAuthService.enqueue(jsonResponse("""
                {"valid": false, "username": null, "roles": null, "error": "expired"}
                """));

        mockMvc.perform(post("/api/payments")
                        .header("Authorization", "Bearer expired-token")
                        .contentType(APPLICATION_JSON)
                        .content(paymentBody()))
                .andExpect(status().isUnauthorized());

        mockAuthService.takeRequest(1, TimeUnit.SECONDS);
    }

    @Test
    void rejectsPaymentWhenAuthorizationHeaderMissing() throws Exception {
        mockMvc.perform(post("/api/payments")
                        .contentType(APPLICATION_JSON)
                        .content(paymentBody()))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void returns502WhenAuthServiceIsUnreachable() throws Exception {
        mockAuthService.enqueue(new MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START));

        mockMvc.perform(post("/api/payments")
                        .header("Authorization", "Bearer some-token")
                        .contentType(APPLICATION_JSON)
                        .content(paymentBody()))
                .andExpect(status().isBadGateway());

        mockAuthService.takeRequest(1, TimeUnit.SECONDS);
    }

    @Test
    void returns404WhenLedgerAccountNotFound() throws Exception {
        enqueueValidAuth();
        mockLedgerService.enqueue(new MockResponse().setResponseCode(404)
                .setHeader("Content-Type", "application/json")
                .setBody("""
                        {"error": "Account not found: acct-1"}
                        """));

        mockMvc.perform(post("/api/payments")
                        .header("Authorization", "Bearer some-valid-token")
                        .contentType(APPLICATION_JSON)
                        .content(paymentBody()))
                .andExpect(status().isNotFound());

        mockAuthService.takeRequest(1, TimeUnit.SECONDS);
        mockLedgerService.takeRequest(1, TimeUnit.SECONDS);
    }

    @Test
    void returns409WhenLedgerReportsInsufficientFunds() throws Exception {
        enqueueValidAuth();
        mockLedgerService.enqueue(new MockResponse().setResponseCode(409)
                .setHeader("Content-Type", "application/json")
                .setBody("""
                        {"error": "Insufficient funds in account: acct-1"}
                        """));

        mockMvc.perform(post("/api/payments")
                        .header("Authorization", "Bearer some-valid-token")
                        .contentType(APPLICATION_JSON)
                        .content(paymentBody()))
                .andExpect(status().isConflict());

        mockAuthService.takeRequest(1, TimeUnit.SECONDS);
        mockLedgerService.takeRequest(1, TimeUnit.SECONDS);
    }

    @Test
    void returns502WhenLedgerServiceIsUnreachable() throws Exception {
        enqueueValidAuth();
        mockLedgerService.enqueue(new MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START));

        mockMvc.perform(post("/api/payments")
                        .header("Authorization", "Bearer some-valid-token")
                        .contentType(APPLICATION_JSON)
                        .content(paymentBody()))
                .andExpect(status().isBadGateway());

        mockAuthService.takeRequest(1, TimeUnit.SECONDS);
        mockLedgerService.takeRequest(1, TimeUnit.SECONDS);
    }

    @Test
    void paymentStillSucceedsWhenNotificationServiceIsUnreachable() throws Exception {
        enqueueValidAuth();
        enqueueSuccessfulDebit();
        mockNotificationService.enqueue(new MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START));

        mockMvc.perform(post("/api/payments")
                        .header("Authorization", "Bearer some-valid-token")
                        .contentType(APPLICATION_JSON)
                        .content(paymentBody()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("ACCEPTED"))
                .andExpect(jsonPath("$.notificationStatus").value("FAILED"));

        drainAll();
    }

    @Test
    void propagatesCorrelationIdAcrossAllThreeDownstreamCalls() throws Exception {
        enqueueValidAuth();
        enqueueSuccessfulDebit();
        enqueueSuccessfulNotification();

        mockMvc.perform(post("/api/payments")
                        .header("Authorization", "Bearer some-valid-token")
                        .header("X-Correlation-Id", "propagate-me-123")
                        .contentType(APPLICATION_JSON)
                        .content(paymentBody()))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Correlation-Id", "propagate-me-123"));

        assertThat(mockAuthService.takeRequest(1, TimeUnit.SECONDS).getHeader("X-Correlation-Id"))
                .isEqualTo("propagate-me-123");
        assertThat(mockLedgerService.takeRequest(1, TimeUnit.SECONDS).getHeader("X-Correlation-Id"))
                .isEqualTo("propagate-me-123");
        assertThat(mockNotificationService.takeRequest(1, TimeUnit.SECONDS).getHeader("X-Correlation-Id"))
                .isEqualTo("propagate-me-123");
    }

    private void drainAll() throws InterruptedException {
        mockAuthService.takeRequest(1, TimeUnit.SECONDS);
        mockLedgerService.takeRequest(1, TimeUnit.SECONDS);
        mockNotificationService.takeRequest(1, TimeUnit.SECONDS);
    }

    private record PaymentPayload(String accountId, String currency, double amount) {
    }
}
