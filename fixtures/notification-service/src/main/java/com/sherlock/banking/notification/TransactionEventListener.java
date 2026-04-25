package com.sherlock.banking.notification;

import com.sherlock.banking.domain.events.TransactionCreatedEvent;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class TransactionEventListener {

    private static final Logger log = LoggerFactory.getLogger(TransactionEventListener.class);

    private final CustomerServiceClient customerClient;

    public TransactionEventListener(CustomerServiceClient customerClient) {
        this.customerClient = customerClient;
    }

    @KafkaListener(topics = "banking.transactions.created", groupId = "notification-service")
    public void onTransactionCreated(TransactionCreatedEvent event) {
        // fan out a notification using the customer's email from customer-service
        String customerId = "cust-" + event.fromAccount().value();
        String email = customerClient.lookupEmail(customerId);
        log.info("Sending txn notification to {} for tx={}", email, event.transactionId());
    }
}
