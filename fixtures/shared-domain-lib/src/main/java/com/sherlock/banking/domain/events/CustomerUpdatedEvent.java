package com.sherlock.banking.domain.events;

import java.time.Instant;

import com.sherlock.banking.domain.CustomerId;

public record CustomerUpdatedEvent(
        CustomerId customerId,
        String fieldChanged,
        String oldValue,
        String newValue,
        Instant occurredAt) {}
