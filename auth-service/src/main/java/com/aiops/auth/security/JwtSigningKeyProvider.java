package com.aiops.auth.security;

import io.jsonwebtoken.security.Keys;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Mutable holder for the JWT signing/verification key, used by JwtService.
 *
 * INTENTIONAL FAULT-INJECTION SUPPORT: this class exists so the AUTH_KEY_ERROR controlled
 * fault (see fault.AuthFaultController) can swap the active key at runtime without touching
 * JwtService's business logic. Normal request handling always reads getActiveKey(); nothing
 * about this changes token issuance/validation semantics when no fault is active.
 */
@Component
public class JwtSigningKeyProvider {

    private static final Logger log = LoggerFactory.getLogger(JwtSigningKeyProvider.class);

    private final SecretKey originalKey;
    private final AtomicReference<SecretKey> activeKey;

    public JwtSigningKeyProvider(@Value("${app.jwt.secret}") String configuredSecret) {
        this.originalKey = Keys.hmacShaKeyFor(configuredSecret.getBytes(StandardCharsets.UTF_8));
        this.activeKey = new AtomicReference<>(originalKey);
    }

    public SecretKey getActiveKey() {
        return activeKey.get();
    }

    public boolean isFaultActive() {
        return activeKey.get() != originalKey;
    }

    /**
     * Swaps in a freshly generated, random, in-memory-only key - never the configured secret,
     * never persisted or logged. Existing tokens (signed with the original key) will fail
     * verification while this fault is active. 64 bytes (512 bits) so the fault key is always
     * large enough for HS256/384/512, regardless of the configured secret's length - this keeps
     * the failure a clean signature mismatch rather than a "key too weak" configuration error.
     */
    public void injectFault() {
        SecretKey faultyKey = Keys.hmacShaKeyFor(randomBytes(64));
        activeKey.set(faultyKey);
        log.warn("[FAULT INJECTION] auth-key-error ENABLED: JWT signing/verification key replaced " +
                "with a random in-memory key. Existing tokens will fail validation until reset.");
    }

    public void reset() {
        activeKey.set(originalKey);
        log.info("[FAULT INJECTION] auth-key-error RESET: original configured JWT key restored.");
    }

    private static byte[] randomBytes(int length) {
        byte[] bytes = new byte[length];
        new SecureRandom().nextBytes(bytes);
        return bytes;
    }
}
