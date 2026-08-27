package com.aiops.payment.client;

import com.aiops.payment.exception.AccountNotFoundException;
import com.aiops.payment.exception.InsufficientFundsException;
import com.aiops.payment.exception.UpstreamServiceUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.math.BigDecimal;
import java.time.Duration;

@Component
public class LedgerServiceClient {

    private static final Logger log = LoggerFactory.getLogger(LedgerServiceClient.class);

    private final WebClient ledgerServiceWebClient;
    private final Duration timeout;

    public LedgerServiceClient(WebClient ledgerServiceWebClient,
                                @Value("${app.ledger-service.timeout-ms}") long timeoutMs) {
        this.ledgerServiceWebClient = ledgerServiceWebClient;
        this.timeout = Duration.ofMillis(timeoutMs);
    }

    /**
     * Debits an account via ledger-service.
     *
     * @throws AccountNotFoundException          if the account doesn't exist.
     * @throws InsufficientFundsException        if the account's balance is too low.
     * @throws UpstreamServiceUnavailableException if ledger-service cannot be reached or times out.
     */
    public LedgerTransactionResponse debit(String accountId, String currency, BigDecimal amount) {
        LedgerTransactionResponse response;
        try {
            response = ledgerServiceWebClient.post()
                    .uri("/api/ledger/debit")
                    .bodyValue(new LedgerDebitRequest(accountId, currency, amount))
                    .retrieve()
                    .onStatus(status -> status.value() == 404,
                            clientResponse -> Mono.error(new AccountNotFoundException(accountId)))
                    .onStatus(status -> status.value() == 409,
                            clientResponse -> Mono.error(new InsufficientFundsException(accountId)))
                    .bodyToMono(LedgerTransactionResponse.class)
                    .block(timeout);
        } catch (AccountNotFoundException | InsufficientFundsException e) {
            throw e;
        } catch (RuntimeException e) {
            // Covers WebClientException (HTTP/connection errors), IllegalStateException (block()
            // timeout), and low-level Reactor Netty failures that don't share a common checked type.
            log.error("Failed to reach ledger-service for debit", e);
            throw new UpstreamServiceUnavailableException("ledger-service", "unavailable", e);
        }

        if (response == null) {
            log.error("Ledger service returned no response for debit");
            throw new UpstreamServiceUnavailableException("ledger-service", "returned no response", null);
        }
        return response;
    }
}
