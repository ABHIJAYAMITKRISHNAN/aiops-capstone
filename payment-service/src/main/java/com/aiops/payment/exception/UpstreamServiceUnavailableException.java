package com.aiops.payment.exception;

/**
 * Thrown when a downstream service call (auth-service, ledger-service, ...) cannot be
 * reached, times out, or returns no usable response.
 */
public class UpstreamServiceUnavailableException extends RuntimeException {

    public UpstreamServiceUnavailableException(String serviceName, String message, Throwable cause) {
        super(serviceName + ": " + message, cause);
    }
}
