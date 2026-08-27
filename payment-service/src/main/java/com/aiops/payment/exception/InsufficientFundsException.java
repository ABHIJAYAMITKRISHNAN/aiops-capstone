package com.aiops.payment.exception;

public class InsufficientFundsException extends RuntimeException {

    public InsufficientFundsException(String accountId) {
        super("Insufficient funds in account: " + accountId);
    }
}
