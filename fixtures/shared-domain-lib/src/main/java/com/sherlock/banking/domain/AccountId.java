package com.sherlock.banking.domain;

public record AccountId(String value) {
    public static AccountId of(String value) {
        return new AccountId(value);
    }
}
