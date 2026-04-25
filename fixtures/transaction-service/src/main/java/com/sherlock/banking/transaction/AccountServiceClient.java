package com.sherlock.banking.transaction;

import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * HTTP client for the downstream account-service.
 * A breaking change to account-service's GET /accounts/{id} or GET /accounts/{id}/balance
 * will impact this service.
 */
@Component
public class AccountServiceClient {

    private final RestClient http;

    public AccountServiceClient(@Value("${clients.account-service.url:http://account-service:8080}") String baseUrl) {
        this.http = RestClient.builder().baseUrl(baseUrl).build();
    }

    public void requireActive(String accountId) {
        Map<?, ?> body = http.get()
                .uri("/accounts/{id}", accountId)
                .retrieve()
                .body(Map.class);
        if (body == null || !"ACTIVE".equals(body.get("status"))) {
            throw new IllegalStateException("account not active: " + accountId);
        }
    }

    /**
     * Reads the account balance using a URI-builder lambda so we can attach a query
     * parameter for the regulatory-reporting currency. The path literal lives inside
     * the lambda's `.path("...")` call — invisible to the simple regex extractor;
     * tree-sitter walks the lambda body and recovers it.
     */
    public Map<?, ?> readBalance(String accountId, String currency) {
        return http.get()
                .uri(b -> b.path("/accounts/{id}/balance")
                        .queryParam("ccy", currency)
                        .build(accountId))
                .retrieve()
                .body(Map.class);
    }
}
