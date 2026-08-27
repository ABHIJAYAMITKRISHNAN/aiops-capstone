package com.aiops.ledger.fault;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * INTENTIONAL FAULT-INJECTION MECHANISM for the DB_POOL_EXHAUSTION controlled experiment (see
 * CLAUDE.md's "Fault injection" section). Disabled by default. Acquires and holds idle JDBC
 * connections directly from the HikariCP-backed DataSource (bypassing JPA/EntityManager
 * entirely - LedgerService is untouched) to create real connection-pool contention for other
 * requests, without ever running any locking SQL - so this can never cause a real database
 * deadlock, only pool pressure.
 *
 * Safety: the number of connections held is clamped to (maximumPoolSize - 1), so this fault can
 * never itself exhaust 100% of the pool or block its own reset from acquiring what it needs.
 */
@Component
public class DbLockFaultService {

    private static final Logger log = LoggerFactory.getLogger(DbLockFaultService.class);

    private final List<Connection> heldConnections = new CopyOnWriteArrayList<>();
    private final AtomicBoolean enabled = new AtomicBoolean(false);

    private final DataSource dataSource;
    private final int requestedHoldCount;
    private final int maximumPoolSize;

    public DbLockFaultService(DataSource dataSource,
                               @Value("${app.fault.db-lock.connections-to-hold:9}") int requestedHoldCount,
                               @Value("${spring.datasource.hikari.maximum-pool-size:10}") int maximumPoolSize) {
        this.dataSource = dataSource;
        this.requestedHoldCount = requestedHoldCount;
        this.maximumPoolSize = maximumPoolSize;
    }

    public synchronized InjectResult inject() {
        if (enabled.get()) {
            return new InjectResult(true, heldConnections.size(), "Fault already active; no additional connections acquired.");
        }

        // Never hold every connection in the pool - always leave at least one free.
        int safeHoldCount = Math.min(requestedHoldCount, maximumPoolSize - 1);
        int acquired = 0;
        try {
            for (int i = 0; i < safeHoldCount; i++) {
                heldConnections.add(dataSource.getConnection());
                acquired++;
            }
            enabled.set(true);
            log.warn("[FAULT INJECTION] db-pool-exhaustion ENABLED: holding {} of {} pool connections open.",
                    acquired, maximumPoolSize);
            return new InjectResult(true, acquired,
                    "DB pool exhaustion fault injected: holding " + acquired + " of " + maximumPoolSize + " connections.");
        } catch (SQLException e) {
            log.error("[FAULT INJECTION] db-pool-exhaustion: failed to acquire connection #{} - releasing what was acquired so far", acquired + 1, e);
            releaseAll();
            return new InjectResult(false, 0, "Failed to acquire connections: " + e.getMessage());
        }
    }

    public synchronized ResetResult reset() {
        int released = releaseAll();
        enabled.set(false);
        log.info("[FAULT INJECTION] db-pool-exhaustion RESET: released {} held connections.", released);
        return new ResetResult(released);
    }

    private int releaseAll() {
        int count = 0;
        for (Connection connection : heldConnections) {
            try {
                connection.close();
                count++;
            } catch (SQLException e) {
                log.warn("[FAULT INJECTION] db-pool-exhaustion: error closing a held connection during reset", e);
            }
        }
        heldConnections.clear();
        return count;
    }

    public boolean isEnabled() {
        return enabled.get();
    }

    public int getHeldConnectionCount() {
        return heldConnections.size();
    }

    public record InjectResult(boolean success, int connectionsHeld, String message) {
    }

    public record ResetResult(int connectionsReleased) {
    }
}
