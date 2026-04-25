package com.sherlock.banking.account;

import java.math.BigDecimal;
import java.util.Optional;

import com.sherlock.banking.domain.AccountId;
import com.sherlock.banking.domain.Money;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * Reads the ledger schema, which is written by the legacy COBOL batch job.
 * Cross-service coupling: a schema change in legacy-ledger breaks this component.
 */
@Component
public class LedgerReader {

    private final JdbcTemplate jdbc;

    public LedgerReader(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<Money> currentBalance(AccountId accountId) {
        String sql = "SELECT amount, currency FROM ledger.balances WHERE account_id = ? ORDER BY posted_at DESC LIMIT 1";
        return jdbc.query(sql, rs -> {
            if (rs.next()) {
                return Optional.of(new Money(rs.getBigDecimal("amount"), rs.getString("currency")));
            }
            return Optional.<Money>empty();
        }, accountId.value());
    }
}
