package com.aiops.notification.controller;

import com.aiops.notification.fault.LatencyFaultState;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class NotificationControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private LatencyFaultState latencyFaultState;

    @AfterEach
    void resetFault() {
        // safety net: never leave the latency fault active across tests
        latencyFaultState.reset();
    }

    @Test
    void sendReceiptReturnsSentStatus() throws Exception {
        String body = objectMapper.writeValueAsString(
                new ReceiptPayload("acct-42", "USD", new BigDecimal("100.50"), "tx-123", "alice"));

        mockMvc.perform(post("/api/notifications/receipt").contentType(APPLICATION_JSON).content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("SENT"))
                .andExpect(jsonPath("$.notificationId").isNotEmpty())
                .andExpect(jsonPath("$.sentAt").isNotEmpty());
    }

    @Test
    void responseCarriesCorrelationIdHeader() throws Exception {
        String body = objectMapper.writeValueAsString(
                new ReceiptPayload("acct-42", "USD", new BigDecimal("100.50"), "tx-123", "alice"));

        mockMvc.perform(post("/api/notifications/receipt")
                        .contentType(APPLICATION_JSON)
                        .header("X-Correlation-Id", "notif-test-1")
                        .content(body))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Correlation-Id", "notif-test-1"));
    }

    @Test
    void rejectsInvalidPayload() throws Exception {
        String body = objectMapper.writeValueAsString(
                new ReceiptPayload("", "USD", new BigDecimal("100.50"), "tx-123", "alice"));

        mockMvc.perform(post("/api/notifications/receipt").contentType(APPLICATION_JSON).content(body))
                .andExpect(status().isBadRequest());
    }

    @Test
    void latencyFaultDelaysResponseUntilReset() throws Exception {
        String body = objectMapper.writeValueAsString(
                new ReceiptPayload("acct-42", "USD", new BigDecimal("100.50"), "tx-123", "alice"));

        long baselineStart = System.currentTimeMillis();
        mockMvc.perform(post("/api/notifications/receipt").contentType(APPLICATION_JSON).content(body))
                .andExpect(status().isOk());
        long baselineElapsed = System.currentTimeMillis() - baselineStart;

        latencyFaultState.inject(150L); // short override so the test suite stays fast
        assertThat(latencyFaultState.isEnabled()).isTrue();

        long faultStart = System.currentTimeMillis();
        mockMvc.perform(post("/api/notifications/receipt").contentType(APPLICATION_JSON).content(body))
                .andExpect(status().isOk());
        long faultElapsed = System.currentTimeMillis() - faultStart;

        assertThat(faultElapsed).isGreaterThanOrEqualTo(150L);
        assertThat(faultElapsed).isGreaterThan(baselineElapsed);

        latencyFaultState.reset();
        assertThat(latencyFaultState.isEnabled()).isFalse();

        long afterResetStart = System.currentTimeMillis();
        mockMvc.perform(post("/api/notifications/receipt").contentType(APPLICATION_JSON).content(body))
                .andExpect(status().isOk());
        long afterResetElapsed = System.currentTimeMillis() - afterResetStart;

        assertThat(afterResetElapsed).isLessThan(150L);
    }

    private record ReceiptPayload(String accountId, String currency, BigDecimal amount,
                                   String transactionId, String recipientUsername) {
    }
}
