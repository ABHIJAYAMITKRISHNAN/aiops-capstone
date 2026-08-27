package com.aiops.payment.config;

import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.ClientRequest;
import org.springframework.web.reactive.function.client.ExchangeFilterFunction;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

@Configuration
public class WebClientConfig {

    private final WebClient.Builder webClientBuilder;

    /**
     * Spring Boot's auto-configured WebClient.Builder (WebClientAutoConfiguration), used instead
     * of the static WebClient.builder(). Now that Actuator/Micrometer are on the classpath, this
     * builder is pre-wired with an ObservationRegistry-backed customizer that records
     * http.client.requests metrics for every WebClient built from it - purely additive
     * observability, no change to baseUrl, filters, or timeout behavior.
     */
    public WebClientConfig(WebClient.Builder webClientBuilder) {
        this.webClientBuilder = webClientBuilder;
    }

    @Bean
    public WebClient authServiceWebClient(@Value("${app.auth-service.base-url}") String baseUrl) {
        return buildClient(baseUrl);
    }

    @Bean
    public WebClient ledgerServiceWebClient(@Value("${app.ledger-service.base-url}") String baseUrl) {
        return buildClient(baseUrl);
    }

    @Bean
    public WebClient notificationServiceWebClient(@Value("${app.notification-service.base-url}") String baseUrl) {
        return buildClient(baseUrl);
    }

    private WebClient buildClient(String baseUrl) {
        // .clone() so each of the three clients above gets its own builder state instead of
        // mutating the shared singleton bean.
        return webClientBuilder.clone()
                .baseUrl(baseUrl)
                .filter(propagateCorrelationId())
                .build();
    }

    /**
     * Copies the current request's correlation ID (held in MDC by CorrelationIdFilter)
     * onto every outbound call made through this WebClient.
     */
    private ExchangeFilterFunction propagateCorrelationId() {
        return ExchangeFilterFunction.ofRequestProcessor(request -> {
            String correlationId = MDC.get(CorrelationIdFilter.MDC_KEY);
            if (correlationId != null) {
                return Mono.just(ClientRequest.from(request)
                        .header(CorrelationIdFilter.HEADER_NAME, correlationId)
                        .build());
            }
            return Mono.just(request);
        });
    }
}
