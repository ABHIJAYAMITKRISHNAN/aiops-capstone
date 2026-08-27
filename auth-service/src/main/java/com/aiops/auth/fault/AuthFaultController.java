package com.aiops.auth.fault;

import com.aiops.auth.security.JwtSigningKeyProvider;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * INTENTIONAL FAULT-INJECTION ENDPOINTS for the AUTH_KEY_ERROR controlled experiment (see
 * CLAUDE.md's "Fault injection" section and the project's Week 4 roadmap). Not part of the
 * normal auth-service API contract. Disabled by default; only active between a call to
 * /inject-auth-key-error and the matching /reset-auth-key.
 */
@RestController
public class AuthFaultController {

    private final JwtSigningKeyProvider signingKeyProvider;

    public AuthFaultController(JwtSigningKeyProvider signingKeyProvider) {
        this.signingKeyProvider = signingKeyProvider;
    }

    @PostMapping("/inject-auth-key-error")
    public FaultStatus injectFault() {
        signingKeyProvider.injectFault();
        return new FaultStatus(true, "Auth key error fault injected. JWT validation will fail for tokens issued before this point.");
    }

    @PostMapping("/reset-auth-key")
    public FaultStatus reset() {
        signingKeyProvider.reset();
        return new FaultStatus(false, "Auth key error fault reset. Original JWT key restored.");
    }

    public record FaultStatus(boolean faultActive, String message) {
    }
}
