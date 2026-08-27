package com.aiops.payment.client;

/**
 * Mirrors auth-service's ValidateRequest contract (POST /api/auth/validate).
 */
record AuthValidateRequest(String token) {
}
