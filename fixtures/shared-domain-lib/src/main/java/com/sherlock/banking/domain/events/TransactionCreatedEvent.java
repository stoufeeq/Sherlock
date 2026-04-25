package com.sherlock.banking.domain.events;

import java.time.Instant;

import com.sherlock.banking.domain.AccountId;
import com.sherlock.banking.domain.Money;
import com.sherlock.banking.domain.TransactionType;

public record TransactionCreatedEvent(
        String transactionId,
        AccountId fromAccount,
        AccountId toAccount,
        Money amount,
        TransactionType type,
        Instant occurredAt) {}
