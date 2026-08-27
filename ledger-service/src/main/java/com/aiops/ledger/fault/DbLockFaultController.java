package com.aiops.ledger.fault;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * INTENTIONAL FAULT-INJECTION ENDPOINTS for the DB_POOL_EXHAUSTION controlled experiment. Not
 * part of the normal ledger-service API contract. See DbLockFaultService for the mechanism and
 * its safety guarantees.
 */
@RestController
public class DbLockFaultController {

    private final DbLockFaultService dbLockFaultService;

    public DbLockFaultController(DbLockFaultService dbLockFaultService) {
        this.dbLockFaultService = dbLockFaultService;
    }

    @PostMapping("/inject-db-lock")
    public DbLockFaultService.InjectResult inject() {
        return dbLockFaultService.inject();
    }

    @PostMapping("/reset-db-lock")
    public DbLockFaultService.ResetResult reset() {
        return dbLockFaultService.reset();
    }
}
