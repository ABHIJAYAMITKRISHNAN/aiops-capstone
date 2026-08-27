package com.aiops.auth.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class JwtServiceTest {

    private final JwtSigningKeyProvider keyProvider =
            new JwtSigningKeyProvider("test-secret-key-that-is-long-enough-for-hmac-sha256");
    private final JwtService jwtService = new JwtService(keyProvider, 60_000L);

    @Test
    void generatesTokenThatCanBeParsedBack() {
        String token = jwtService.generateToken("alice", List.of("USER", "ADMIN"));

        Claims claims = jwtService.parseAndValidate(token);

        assertThat(claims.getSubject()).isEqualTo("alice");
        assertThat(jwtService.extractRoles(claims)).containsExactly("USER", "ADMIN");
    }

    @Test
    void rejectsTokenSignedWithDifferentKey() {
        JwtSigningKeyProvider otherKeyProvider = new JwtSigningKeyProvider("a-completely-different-secret-key-value");
        JwtService otherService = new JwtService(otherKeyProvider, 60_000L);
        String token = otherService.generateToken("bob", List.of("USER"));

        assertThatThrownBy(() -> jwtService.parseAndValidate(token))
                .isInstanceOf(JwtException.class);
    }

    @Test
    void rejectsMalformedToken() {
        assertThatThrownBy(() -> jwtService.parseAndValidate("not-a-jwt"))
                .isInstanceOf(JwtException.class);
    }

    @Test
    void rejectsExpiredToken() throws InterruptedException {
        JwtSigningKeyProvider shortLivedKeyProvider =
                new JwtSigningKeyProvider("test-secret-key-that-is-long-enough-for-hmac-sha256");
        JwtService shortLived = new JwtService(shortLivedKeyProvider, 1L);
        String token = shortLived.generateToken("alice", List.of("USER"));
        Thread.sleep(10);

        assertThatThrownBy(() -> shortLived.parseAndValidate(token))
                .isInstanceOf(JwtException.class);
    }

    @Test
    void faultInjectionBreaksPreviouslyIssuedTokensUntilReset() {
        String tokenBeforeFault = jwtService.generateToken("alice", List.of("USER"));
        assertThat(jwtService.parseAndValidate(tokenBeforeFault).getSubject()).isEqualTo("alice");

        keyProvider.injectFault();
        assertThat(keyProvider.isFaultActive()).isTrue();
        assertThatThrownBy(() -> jwtService.parseAndValidate(tokenBeforeFault))
                .isInstanceOf(JwtException.class);

        keyProvider.reset();
        assertThat(keyProvider.isFaultActive()).isFalse();
        assertThat(jwtService.parseAndValidate(tokenBeforeFault).getSubject()).isEqualTo("alice");
    }
}
