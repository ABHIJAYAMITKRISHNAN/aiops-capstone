package com.aiops.payment.fault;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/**
 * INTENTIONAL FAULT-INJECTION MECHANISM for the MEMORY_LEAK controlled experiment (see
 * CLAUDE.md's "Fault injection" section). Disabled by default. When enabled, periodically
 * allocates byte[] chunks and retains references to them (simulating a leak) until reset, which
 * clears the list and makes everything eligible for garbage collection again.
 *
 * Safety: allocation stops once maxTotalBytes is reached, so this can never grow unbounded and
 * cannot exhaust host memory on its own - it is capped well below typical container/JVM limits.
 */
@Component
public class MemoryLeakFaultService {

    private static final Logger log = LoggerFactory.getLogger(MemoryLeakFaultService.class);

    private final List<byte[]> retainedChunks = Collections.synchronizedList(new java.util.ArrayList<>());
    private final AtomicBoolean enabled = new AtomicBoolean(false);
    private final AtomicLong retainedBytes = new AtomicLong(0);

    private final int chunkSizeBytes;
    private final long maxTotalBytes;

    public MemoryLeakFaultService(
            @Value("${app.fault.memory-leak.chunk-size-bytes:5000000}") int chunkSizeBytes,
            @Value("${app.fault.memory-leak.max-total-bytes:200000000}") long maxTotalBytes) {
        this.chunkSizeBytes = chunkSizeBytes;
        this.maxTotalBytes = maxTotalBytes;
    }

    public void inject() {
        enabled.set(true);
        log.warn("[FAULT INJECTION] memory-leak ENABLED: allocating ~{} bytes every scheduled tick, " +
                "capped at {} bytes total.", chunkSizeBytes, maxTotalBytes);
    }

    public void reset() {
        enabled.set(false);
        int clearedChunks = retainedChunks.size();
        long clearedBytes = retainedBytes.getAndSet(0);
        retainedChunks.clear();
        log.info("[FAULT INJECTION] memory-leak RESET: allocation stopped, {} retained chunks " +
                "({} bytes) cleared and eligible for GC.", clearedChunks, clearedBytes);
    }

    public boolean isEnabled() {
        return enabled.get();
    }

    public long getRetainedBytes() {
        return retainedBytes.get();
    }

    public int getRetainedChunkCount() {
        return retainedChunks.size();
    }

    @Scheduled(fixedDelayString = "${app.fault.memory-leak.interval-ms:1000}")
    void allocateIfEnabled() {
        if (!enabled.get()) {
            return;
        }
        if (retainedBytes.get() + chunkSizeBytes > maxTotalBytes) {
            return; // next chunk would breach the cap - stop growing, but stay "enabled" until explicitly reset
        }
        retainedChunks.add(new byte[chunkSizeBytes]);
        long total = retainedBytes.addAndGet(chunkSizeBytes);
        log.debug("[FAULT INJECTION] memory-leak: allocated {} bytes (total retained: {})", chunkSizeBytes, total);
    }
}
