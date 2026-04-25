package com.sherlock.banking.transaction;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.time.LocalDate;
import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Nightly batch job: flushes the day's transaction postings to a shared-volume
 * fixed-width file that the legacy-ledger COBOL batch picks up at 02:00.
 *
 * File contract:
 *   Path:   /shared/postings/POSTINGS.DAT
 *   Format: one posting per line — ACCOUNT-ID(16) AMOUNT(18 signed) CURRENCY(3)
 *
 * Changing this path or format BREAKS legacy-ledger. Sherlock should flag it.
 */
@Component
public class NightlyPostingsFeedWriter {

    private static final Logger log = LoggerFactory.getLogger(NightlyPostingsFeedWriter.class);

    private static final Path OUTPUT_PATH = Paths.get("/shared/postings/POSTINGS.DAT");

    @Scheduled(cron = "0 0 1 * * ?")  // 01:00 daily
    public void flushDailyPostings() throws IOException {
        Files.createDirectories(OUTPUT_PATH.getParent());
        List<String> lines = collectPostingsForDay(LocalDate.now());
        try (BufferedWriter w = Files.newBufferedWriter(OUTPUT_PATH,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)) {
            for (String line : lines) {
                w.write(line);
                w.newLine();
            }
        }
        log.info("wrote {} postings to {}", lines.size(), OUTPUT_PATH);
    }

    private List<String> collectPostingsForDay(LocalDate day) {
        // Real impl would query the transactions.transactions table; stubbed for fixture.
        return List.of();
    }
}
