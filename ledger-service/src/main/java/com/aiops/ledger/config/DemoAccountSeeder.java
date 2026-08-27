package com.aiops.ledger.config;

import com.aiops.ledger.repository.AccountRepository;
import com.aiops.ledger.service.LedgerService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;

/**
 * Seeds a single demo account ("acct-42") on startup so the synchronous payment chain has
 * something to debit against without a real account-provisioning flow. Placeholder for Week 2,
 * same spirit as auth-service's hardcoded UserStore; disable with app.seed-demo-account=false.
 */
@Component
public class DemoAccountSeeder implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(DemoAccountSeeder.class);
    private static final String DEMO_ACCOUNT_ID = "acct-42";

    private final AccountRepository accountRepository;
    private final LedgerService ledgerService;
    private final boolean enabled;

    public DemoAccountSeeder(AccountRepository accountRepository,
                              LedgerService ledgerService,
                              @Value("${app.seed-demo-account:true}") boolean enabled) {
        this.accountRepository = accountRepository;
        this.ledgerService = ledgerService;
        this.enabled = enabled;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (!enabled) {
            return;
        }
        if (accountRepository.findByAccountId(DEMO_ACCOUNT_ID).isPresent()) {
            log.info("Demo account '{}' already exists, skipping seed", DEMO_ACCOUNT_ID);
            return;
        }
        ledgerService.createAccount(DEMO_ACCOUNT_ID, "USD", new BigDecimal("1000.00"));
        log.info("Seeded demo account '{}' with balance 1000.00 USD", DEMO_ACCOUNT_ID);
    }
}
