package com.sherlock.banking.transaction;

import com.sherlock.banking.domain.events.TransactionCreatedEvent;

import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;

@Component
public class TransactionEventPublisher {

    public static final String TOPIC = "banking.transactions.created";

    private final KafkaTemplate<String, TransactionCreatedEvent> kafka;

    public TransactionEventPublisher(KafkaTemplate<String, TransactionCreatedEvent> kafka) {
        this.kafka = kafka;
    }

    public void publish(TransactionCreatedEvent event) {
        kafka.send(TOPIC, event.transactionId(), event);
    }
}
