package com.aiops.ledger.exception;

public class CurrencyMismatchException extends RuntimeException {

    public CurrencyMismatchException(String accountId, String accountCurrency, String requestCurrency) {
        super("Account " + accountId + " holds " + accountCurrency + ", but request was in " + requestCurrency);
    }
}
