package com.aiops.auth.dto;

import jakarta.validation.constraints.NotBlank;

public record ValidateRequest(
        @NotBlank String token
) {
}
