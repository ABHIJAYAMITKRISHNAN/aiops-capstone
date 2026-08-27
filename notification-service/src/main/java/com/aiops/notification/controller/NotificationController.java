package com.aiops.notification.controller;

import com.aiops.notification.dto.ReceiptRequest;
import com.aiops.notification.dto.ReceiptResponse;
import com.aiops.notification.fault.LatencyFaultState;
import jakarta.validation.Valid;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.UUID;

/**
 * Simulates sending a payment receipt. No real email/SMS integration - this just logs the
 * receipt activity, per the Notification Service's Week 2 scope.
 */
@RestController
@RequestMapping("/api/notifications")
public class NotificationController {

    private static final Logger log = LoggerFactory.getLogger(NotificationController.class);

    private final LatencyFaultState latencyFaultState;

    public NotificationController(LatencyFaultState latencyFaultState) {
        this.latencyFaultState = latencyFaultState;
    }

    @PostMapping("/receipt")
    public ReceiptResponse sendReceipt(@Valid @RequestBody ReceiptRequest request) throws InterruptedException {
        // INTENTIONAL FAULT INJECTION (NOTIFICATION_LATENCY controlled experiment): sleeps before
        // responding only while the fault is active (disabled by default). See fault package.
        if (latencyFaultState.isEnabled()) {
            Thread.sleep(latencyFaultState.getDelayMs());
        }

        String notificationId = UUID.randomUUID().toString();
        log.info("Simulated receipt sent to '{}' for transaction '{}': {} {} on account '{}' (notificationId={})",
                request.recipientUsername(), request.transactionId(), request.amount(), request.currency(),
                request.accountId(), notificationId);

        return new ReceiptResponse(notificationId, "SENT", Instant.now());
    }
}
