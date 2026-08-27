package com.aiops.payment.client;

import java.math.BigDecimal;

/**
 * Mirrors notification-service's ReceiptRequest contract (POST /api/notifications/receipt).
 */
record NotificationReceiptRequest(String accountId, String currency, BigDecimal amount,
                                   String transactionId, String recipientUsername) {
}
