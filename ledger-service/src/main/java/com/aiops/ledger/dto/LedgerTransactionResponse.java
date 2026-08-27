package com.aiops.ledger.dto;

import com.aiops.ledger.model.LedgerTransaction;

import java.math.BigDecimal;
import java.time.Instant;

public record LedgerTransactionResponse(
        String transactionId,
        String accountId,
        String type,
        BigDecimal amount,
        String currency,
        BigDecimal balanceAfter,
        Instant createdAt
) {
    public static LedgerTransactionResponse from(LedgerTransaction tx) {
        return new LedgerTransactionResponse(
                tx.getTransactionId(),
                tx.getAccount().getAccountId(),
                tx.getType().name(),
                tx.getAmount(),
                tx.getCurrency(),
                tx.getBalanceAfter(),
                tx.getCreatedAt());
    }
}
