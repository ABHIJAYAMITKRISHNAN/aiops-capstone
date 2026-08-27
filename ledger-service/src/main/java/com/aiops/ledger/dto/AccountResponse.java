package com.aiops.ledger.dto;

import com.aiops.ledger.model.Account;

import java.math.BigDecimal;

public record AccountResponse(String accountId, String currency, BigDecimal balance) {

    public static AccountResponse from(Account account) {
        return new AccountResponse(account.getAccountId(), account.getCurrency(), account.getBalance());
    }
}
