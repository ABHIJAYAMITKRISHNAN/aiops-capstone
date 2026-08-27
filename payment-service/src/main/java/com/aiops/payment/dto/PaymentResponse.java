package com.aiops.payment.dto;

public record PaymentResponse(
        String status,
        String message,
        String authenticatedUser,
        String ledgerTransactionId,
        String notificationStatus
) {
}
