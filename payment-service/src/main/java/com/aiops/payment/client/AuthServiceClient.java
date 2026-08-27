package com.aiops.payment.client;

import com.aiops.payment.exception.UpstreamServiceUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;

@Component
public class AuthServiceClient {

    private static final Logger log = LoggerFactory.getLogger(AuthServiceClient.class);

    private final WebClient authServiceWebClient;
    private final Duration timeout;

    public AuthServiceClient(WebClient authServiceWebClient,
                              @Value("${app.auth-service.timeout-ms}") long timeoutMs) {
        this.authServiceWebClient = authServiceWebClient;
        this.timeout = Duration.ofMillis(timeoutMs);
    }

    /**
     * Validates a JWT against auth-service.
     *
     * @throws UpstreamServiceUnavailableException if auth-service cannot be reached or times out.
     */
    public AuthValidateResponse validate(String token) {
        AuthValidateResponse response;
        try {
            response = authServiceWebClient.post()
                    .uri("/api/auth/validate")
                    .bodyValue(new AuthValidateRequest(token))
                    .retrieve()
                    .bodyToMono(AuthValidateResponse.class)
                    .block(timeout);
        } catch (RuntimeException e) {
            // Covers WebClientException (HTTP/connection errors), IllegalStateException (block()
            // timeout), and low-level Reactor Netty failures (e.g. connection reset/aborted)
            // that don't share a common checked type.
            log.error("Failed to reach auth-service for token validation", e);
            throw new UpstreamServiceUnavailableException("auth-service", "unavailable", e);
        }

        if (response == null) {
            // A dropped connection can surface as an empty completion rather than an error signal.
            log.error("Auth service returned no response for token validation");
            throw new UpstreamServiceUnavailableException("auth-service", "returned no response", null);
        }
        return response;
    }
}
