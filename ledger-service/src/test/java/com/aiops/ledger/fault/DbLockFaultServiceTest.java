package com.aiops.ledger.fault;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Runs against the real Postgres test database (same as the rest of ledger-service's test
 * suite), since this fault deliberately operates on real JDBC connections from the pool.
 */
@SpringBootTest
class DbLockFaultServiceTest {

    @Autowired
    private DbLockFaultService dbLockFaultService;

    @AfterEach
    void cleanUp() {
        // safety net: never leave connections held across tests, regardless of test outcome
        dbLockFaultService.reset();
    }

    @Test
    void disabledByDefault() {
        assertThat(dbLockFaultService.isEnabled()).isFalse();
        assertThat(dbLockFaultService.getHeldConnectionCount()).isZero();
    }

    @Test
    void injectHoldsConnectionsBelowPoolMax() {
        DbLockFaultService.InjectResult result = dbLockFaultService.inject();

        assertThat(result.success()).isTrue();
        assertThat(result.connectionsHeld()).isEqualTo(9); // configured hold count, pool max is 10
        assertThat(dbLockFaultService.isEnabled()).isTrue();
        assertThat(dbLockFaultService.getHeldConnectionCount()).isEqualTo(9);
    }

    @Test
    void injectIsIdempotentWhileAlreadyActive() {
        dbLockFaultService.inject();
        int firstHeldCount = dbLockFaultService.getHeldConnectionCount();

        DbLockFaultService.InjectResult secondInject = dbLockFaultService.inject();

        assertThat(secondInject.connectionsHeld()).isEqualTo(firstHeldCount);
        assertThat(dbLockFaultService.getHeldConnectionCount()).isEqualTo(firstHeldCount);
    }

    @Test
    void resetReleasesAllHeldConnections() {
        dbLockFaultService.inject();
        assertThat(dbLockFaultService.getHeldConnectionCount()).isGreaterThan(0);

        DbLockFaultService.ResetResult resetResult = dbLockFaultService.reset();

        assertThat(resetResult.connectionsReleased()).isEqualTo(9);
        assertThat(dbLockFaultService.isEnabled()).isFalse();
        assertThat(dbLockFaultService.getHeldConnectionCount()).isZero();
    }

    @Test
    void resetIsSafeWhenNothingIsHeld() {
        DbLockFaultService.ResetResult resetResult = dbLockFaultService.reset();

        assertThat(resetResult.connectionsReleased()).isZero();
        assertThat(dbLockFaultService.isEnabled()).isFalse();
    }

    @Test
    void faultIsRepeatable() {
        dbLockFaultService.inject();
        dbLockFaultService.reset();

        DbLockFaultService.InjectResult secondRun = dbLockFaultService.inject();

        assertThat(secondRun.success()).isTrue();
        assertThat(secondRun.connectionsHeld()).isEqualTo(9);
    }
}
