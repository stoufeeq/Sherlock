package com.sherlock.banking.account;

import java.math.BigDecimal;
import java.util.Map;

import com.sherlock.banking.domain.AccountId;
import com.sherlock.banking.domain.Money;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/accounts")
public class AccountController {

    private final LedgerReader ledger;

    public AccountController(LedgerReader ledger) {
        this.ledger = ledger;
    }

    @GetMapping("/{id}")
    public Map<String, Object> getAccount(@PathVariable String id) {
        return Map.of(
                "id", id,
                "customerId", "cust-" + id,
                "status", "ACTIVE");
    }

    @GetMapping("/{id}/balance")
    public Map<String, Object> getBalance(@PathVariable String id) {
        Money balance = ledger.currentBalance(AccountId.of(id))
                .orElse(new Money(BigDecimal.ZERO, "USD"));
        return Map.of(
                "accountId", id,
                "amount", balance.amount(),
                "currency", balance.currency());
    }
}
