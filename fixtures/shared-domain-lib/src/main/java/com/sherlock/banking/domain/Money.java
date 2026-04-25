package com.sherlock.banking.domain;

import java.math.BigDecimal;

public record Money(BigDecimal amount, String currency) {
    public static Money of(String amount, String currency) {
        return new Money(new BigDecimal(amount), currency);
    }
}
