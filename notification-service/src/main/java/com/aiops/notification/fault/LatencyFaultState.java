package com.aiops.notification.fault;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/**
 * INTENTIONAL FAULT-INJECTION STATE for the NOTIFICATION_LATENCY controlled experiment (see
 * CLAUDE.md's "Fault injection" section). Disabled by default. When enabled,
 * NotificationController sleeps for delayMs before responding, simulating the real-world
 * "Notification Service adds ~6s delay" scenario.
 */
@Component
public class LatencyFaultState {

    private static final Logger log = LoggerFactory.getLogger(LatencyFaultState.class);

    private final AtomicBoolean enabled = new AtomicBoolean(false);
    private final AtomicLong delayMs;
    private final long defaultDelayMs;

    public LatencyFaultState(@Value("${app.fault.notification-latency.default-delay-ms:6000}") long defaultDelayMs) {
        this.defaultDelayMs = defaultDelayMs;
        this.delayMs = new AtomicLong(defaultDelayMs);
    }

    public void inject(Long overrideDelayMs) {
        long delay = (overrideDelayMs != null && overrideDelayMs > 0) ? overrideDelayMs : defaultDelayMs;
        delayMs.set(delay);
        enabled.set(true);
        log.warn("[FAULT INJECTION] notification-latency ENABLED: {}ms delay before every receipt response.", delay);
    }

    public void reset() {
        enabled.set(false);
        delayMs.set(defaultDelayMs);
        log.info("[FAULT INJECTION] notification-latency RESET: responses are immediate again.");
    }

    public boolean isEnabled() {
        return enabled.get();
    }

    public long getDelayMs() {
        return delayMs.get();
    }
}
