package com.aiops.payment.client;

import java.util.List;

/**
 * Mirrors auth-service's ValidateResponse contract (POST /api/auth/validate).
 */
public record AuthValidateResponse(boolean valid, String username, List<String> roles, String error) {
}
