package com.aiops.auth.dto;

import java.util.List;

public record ValidateResponse(
        boolean valid,
        String username,
        List<String> roles,
        String error
) {
    public static ValidateResponse valid(String username, List<String> roles) {
        return new ValidateResponse(true, username, roles, null);
    }

    public static ValidateResponse invalid(String error) {
        return new ValidateResponse(false, null, null, error);
    }
}
