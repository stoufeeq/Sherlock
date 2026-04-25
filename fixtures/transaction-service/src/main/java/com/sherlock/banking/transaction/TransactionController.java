package com.sherlock.banking.transaction;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

import com.sherlock.banking.domain.AccountId;
import com.sherlock.banking.domain.Money;
import com.sherlock.banking.domain.TransactionType;
import com.sherlock.banking.domain.events.TransactionCreatedEvent;

import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/transactions")
public class TransactionController {

    private final AccountServiceClient accountClient;
    private final TransactionEventPublisher publisher;

    public TransactionController(AccountServiceClient accountClient, TransactionEventPublisher publisher) {
        this.accountClient = accountClient;
        this.publisher = publisher;
    }

    @PostMapping
    public Map<String, Object> create(@RequestBody Map<String, Object> req) {
        String fromId = (String) req.get("fromAccountId");
        String toId = (String) req.get("toAccountId");

        // cross-service dep: validate both accounts via account-service
        accountClient.requireActive(fromId);
        accountClient.requireActive(toId);

        String txId = UUID.randomUUID().toString();
        TransactionCreatedEvent event = new TransactionCreatedEvent(
                txId,
                AccountId.of(fromId),
                AccountId.of(toId),
                new Money(new BigDecimal(req.get("amount").toString()), (String) req.get("currency")),
                TransactionType.valueOf((String) req.get("type")),
                Instant.now());

        publisher.publish(event);

        return Map.of(
                "id", txId,
                "fromAccountId", fromId,
                "toAccountId", toId,
                "amount", req.get("amount"),
                "currency", req.get("currency"),
                "type", req.get("type"));
    }
}
