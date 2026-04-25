package com.sherlock.banking.customer;

import java.time.Instant;
import java.util.Map;

import com.sherlock.banking.domain.CustomerId;
import com.sherlock.banking.domain.events.CustomerUpdatedEvent;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/customers")
public class CustomerController {

    private final CustomerEventPublisher publisher;

    public CustomerController(CustomerEventPublisher publisher) {
        this.publisher = publisher;
    }

    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable String id) {
        return Map.of(
                "id", id,
                "fullName", "Jane Doe",
                "email", "jane@example.com");
    }

    @PutMapping("/{id}")
    public Map<String, Object> update(@PathVariable String id, @RequestBody Map<String, Object> req) {
        publisher.publish(new CustomerUpdatedEvent(
                CustomerId.of(id),
                "email",
                null,
                (String) req.get("email"),
                Instant.now()));
        return Map.of(
                "id", id,
                "fullName", req.getOrDefault("fullName", "Jane Doe"),
                "email", req.get("email"));
    }
}
