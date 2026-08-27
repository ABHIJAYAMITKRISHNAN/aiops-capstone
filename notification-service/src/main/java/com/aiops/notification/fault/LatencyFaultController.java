package com.aiops.notification.fault;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/**
 * INTENTIONAL FAULT-INJECTION ENDPOINTS for the NOTIFICATION_LATENCY controlled experiment. Not
 * part of the normal notification-service API contract.
 */
@RestController
public class LatencyFaultController {

    private final LatencyFaultState latencyFaultState;

    public LatencyFaultController(LatencyFaultState latencyFaultState) {
        this.latencyFaultState = latencyFaultState;
    }

    @PostMapping("/inject-latency")
    public FaultStatus inject(@RequestBody(required = false) InjectLatencyRequest request) {
        Long overrideDelayMs = request != null ? request.delayMs() : null;
        latencyFaultState.inject(overrideDelayMs);
        return status("Notification latency fault injected.");
    }

    @PostMapping("/reset-latency")
    public FaultStatus reset() {
        latencyFaultState.reset();
        return status("Notification latency fault reset.");
    }

    /**
     * Read-only status check for the telemetry collector (Week 5) - does not trigger or change
     * the fault in any way.
     */
    @GetMapping("/fault-status")
    public FaultStatus status() {
        return status(latencyFaultState.isEnabled() ? "Notification latency fault is active." : "Notification latency fault is inactive.");
    }

    private FaultStatus status(String message) {
        return new FaultStatus(latencyFaultState.isEnabled(), latencyFaultState.getDelayMs(), message);
    }

    public record InjectLatencyRequest(Long delayMs) {
    }

    public record FaultStatus(boolean faultActive, long delayMs, String message) {
    }
}
