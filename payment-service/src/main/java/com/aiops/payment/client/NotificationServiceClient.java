package com.aiops.payment.client;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;

import java.math.BigDecimal;
import java.time.Duration;

/**
 * Sends the payment receipt notification. This is best-effort: money has already moved in
 * ledger-service by the time this is called, so a notification failure is logged and reported
 * back as a FAILED status rather than failing the whole payment.
 */
@Component
public class NotificationServiceClient {

    private static final Logger log = LoggerFactory.getLogger(NotificationServiceClient.class);

    private final WebClient notificationServiceWebClient;
    private final Duration timeout;

    public NotificationServiceClient(WebClient notificationServiceWebClient,
                                      @Value("${app.notification-service.timeout-ms}") long timeoutMs) {
        this.notificationServiceWebClient = notificationServiceWebClient;
        this.timeout = Duration.ofMillis(timeoutMs);
    }

    public NotificationResult sendReceipt(String accountId, String currency, BigDecimal amount,
                                           String transactionId, String recipientUsername) {
        try {
            NotificationReceiptResponse response = notificationServiceWebClient.post()
                    .uri("/api/notifications/receipt")
                    .bodyValue(new NotificationReceiptRequest(accountId, currency, amount, transactionId, recipientUsername))
                    .retrieve()
                    .bodyToMono(NotificationReceiptResponse.class)
                    .block(timeout);

            if (response == null) {
                log.warn("Notification service returned no response for transaction '{}'", transactionId);
                return NotificationResult.failed();
            }
            return NotificationResult.sent(response.notificationId());
        } catch (RuntimeException e) {
            log.warn("Failed to send receipt notification for transaction '{}': {}", transactionId, e.getMessage());
            return NotificationResult.failed();
        }
    }
}
