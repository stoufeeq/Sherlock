package com.sherlock.banking.customer;

import com.sherlock.banking.domain.events.CustomerUpdatedEvent;

import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;

@Component
public class CustomerEventPublisher {

    public static final String TOPIC = "banking.customers.updated";

    private final KafkaTemplate<String, CustomerUpdatedEvent> kafka;

    public CustomerEventPublisher(KafkaTemplate<String, CustomerUpdatedEvent> kafka) {
        this.kafka = kafka;
    }

    public void publish(CustomerUpdatedEvent event) {
        kafka.send(TOPIC, event.customerId().value(), event);
    }
}
