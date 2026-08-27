package com.aiops.auth.dto;

public record LoginResponse(
        String token,
        String tokenType,
        long expiresInMs
) {
    public LoginResponse(String token, long expiresInMs) {
        this(token, "Bearer", expiresInMs);
    }
}
