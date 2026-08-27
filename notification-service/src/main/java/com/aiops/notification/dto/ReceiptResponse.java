package com.aiops.notification.dto;

import java.time.Instant;

public record ReceiptResponse(String notificationId, String status, Instant sentAt) {
}
