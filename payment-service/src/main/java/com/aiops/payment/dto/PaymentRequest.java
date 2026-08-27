package com.aiops.payment.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;

import java.math.BigDecimal;

public record PaymentRequest(
        @NotBlank String accountId,
        @NotBlank String currency,
        @Positive BigDecimal amount
) {
}
