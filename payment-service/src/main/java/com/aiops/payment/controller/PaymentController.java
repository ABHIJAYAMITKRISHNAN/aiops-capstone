package com.aiops.payment.controller;

import com.aiops.payment.client.AuthServiceClient;
import com.aiops.payment.client.AuthValidateResponse;
import com.aiops.payment.client.LedgerServiceClient;
import com.aiops.payment.client.LedgerTransactionResponse;
import com.aiops.payment.client.NotificationResult;
import com.aiops.payment.client.NotificationServiceClient;
import com.aiops.payment.dto.PaymentRequest;
import com.aiops.payment.dto.PaymentResponse;
import com.aiops.payment.exception.UnauthorizedException;
import jakarta.validation.Valid;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Orchestrates the full synchronous payment chain: validate the caller's JWT with auth-service,
 * debit the account via ledger-service, then send a receipt via notification-service.
 */
@RestController
@RequestMapping("/api/payments")
public class PaymentController {

    private static final Logger log = LoggerFactory.getLogger(PaymentController.class);
    private static final String BEARER_PREFIX = "Bearer ";

    private final AuthServiceClient authServiceClient;
    private final LedgerServiceClient ledgerServiceClient;
    private final NotificationServiceClient notificationServiceClient;

    public PaymentController(AuthServiceClient authServiceClient,
                              LedgerServiceClient ledgerServiceClient,
                              NotificationServiceClient notificationServiceClient) {
        this.authServiceClient = authServiceClient;
        this.ledgerServiceClient = ledgerServiceClient;
        this.notificationServiceClient = notificationServiceClient;
    }

    @PostMapping
    public PaymentResponse submitPayment(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorizationHeader,
                                          @Valid @RequestBody PaymentRequest request) {
        String token = extractBearerToken(authorizationHeader);

        AuthValidateResponse validation = authServiceClient.validate(token);
        if (!validation.valid()) {
            throw new UnauthorizedException("Invalid or expired token");
        }

        LedgerTransactionResponse ledgerTransaction = ledgerServiceClient.debit(
                request.accountId(), request.currency(), request.amount());
        log.info("Ledger debit completed for account {} ({} {}), transactionId={}",
                request.accountId(), request.amount(), request.currency(), ledgerTransaction.transactionId());

        NotificationResult notificationResult = notificationServiceClient.sendReceipt(
                request.accountId(), request.currency(), request.amount(),
                ledgerTransaction.transactionId(), validation.username());

        log.info("Payment accepted for account {} on behalf of user '{}' (notification={})",
                request.accountId(), validation.username(), notificationResult.status());

        return new PaymentResponse(
                "ACCEPTED",
                "Payment processed successfully",
                validation.username(),
                ledgerTransaction.transactionId(),
                notificationResult.status());
    }

    private String extractBearerToken(String authorizationHeader) {
        if (authorizationHeader == null || !authorizationHeader.startsWith(BEARER_PREFIX)) {
            throw new UnauthorizedException("Missing or malformed Authorization header");
        }
        return authorizationHeader.substring(BEARER_PREFIX.length());
    }
}
