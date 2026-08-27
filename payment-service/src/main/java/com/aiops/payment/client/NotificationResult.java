package com.aiops.payment.client;

public record NotificationResult(String status, String notificationId) {

    public static NotificationResult sent(String notificationId) {
        return new NotificationResult("SENT", notificationId);
    }

    public static NotificationResult failed() {
        return new NotificationResult("FAILED", null);
    }
}
