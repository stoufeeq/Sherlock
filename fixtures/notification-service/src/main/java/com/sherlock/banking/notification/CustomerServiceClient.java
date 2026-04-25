package com.sherlock.banking.notification;

import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class CustomerServiceClient {

    private final RestClient http;

    public CustomerServiceClient(@Value("${clients.customer-service.url:http://customer-service:8080}") String baseUrl) {
        this.http = RestClient.builder().baseUrl(baseUrl).build();
    }

    public String lookupEmail(String customerId) {
        Map<?, ?> body = http.get()
                .uri("/customers/{id}", customerId)
                .retrieve()
                .body(Map.class);
        return body != null ? (String) body.get("email") : null;
    }
}
