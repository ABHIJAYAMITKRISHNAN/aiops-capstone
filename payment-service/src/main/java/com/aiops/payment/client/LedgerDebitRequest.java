package com.aiops.payment.client;

import java.math.BigDecimal;

/**
 * Mirrors ledger-service's LedgerOperationRequest contract (POST /api/ledger/debit).
 */
record LedgerDebitRequest(String accountId, String currency, BigDecimal amount) {
}
