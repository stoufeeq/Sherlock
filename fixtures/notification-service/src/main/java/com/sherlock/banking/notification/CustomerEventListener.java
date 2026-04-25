package com.sherlock.banking.notification;

import com.sherlock.banking.domain.events.CustomerUpdatedEvent;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class CustomerEventListener {

    private static final Logger log = LoggerFactory.getLogger(CustomerEventListener.class);

    @KafkaListener(topics = "banking.customers.updated", groupId = "notification-service")
    public void onCustomerUpdated(CustomerUpdatedEvent event) {
        log.info("Customer {} had {} updated — sending confirmation", event.customerId().value(), event.fieldChanged());
    }
}
