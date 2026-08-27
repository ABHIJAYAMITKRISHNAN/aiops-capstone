package com.aiops.payment.client;

import java.math.BigDecimal;
import java.time.Instant;

/**
 * Mirrors ledger-service's LedgerTransactionResponse contract.
 */
public record LedgerTransactionResponse(
        String transactionId,
        String accountId,
        String type,
        BigDecimal amount,
        String currency,
        BigDecimal balanceAfter,
        Instant createdAt
) {
}
