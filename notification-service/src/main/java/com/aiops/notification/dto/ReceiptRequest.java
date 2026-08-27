package com.aiops.notification.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

import java.math.BigDecimal;

public record ReceiptRequest(
        @NotBlank String accountId,
        @NotBlank String currency,
        @NotNull @Positive BigDecimal amount,
        @NotBlank String transactionId,
        @NotBlank String recipientUsername
) {
}
