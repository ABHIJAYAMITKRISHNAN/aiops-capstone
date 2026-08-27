package com.aiops.ledger.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

import java.math.BigDecimal;

public record LedgerOperationRequest(
        @NotBlank String accountId,
        @NotBlank String currency,
        @NotNull @Positive BigDecimal amount
) {
}
