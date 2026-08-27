package com.aiops.auth.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.Date;
import java.util.List;

@Service
public class JwtService {

    private static final String ROLES_CLAIM = "roles";

    private final JwtSigningKeyProvider signingKeyProvider;
    private final long expirationMs;

    public JwtService(JwtSigningKeyProvider signingKeyProvider,
                       @Value("${app.jwt.expiration-ms}") long expirationMs) {
        this.signingKeyProvider = signingKeyProvider;
        this.expirationMs = expirationMs;
    }

    public String generateToken(String username, List<String> roles) {
        Date now = new Date();
        Date expiry = new Date(now.getTime() + expirationMs);

        return Jwts.builder()
                .subject(username)
                .claim(ROLES_CLAIM, roles)
                .issuedAt(now)
                .expiration(expiry)
                .signWith(signingKeyProvider.getActiveKey())
                .compact();
    }

    /**
     * @throws JwtException if the token is malformed, expired, or has an invalid signature.
     */
    public Claims parseAndValidate(String token) {
        return Jwts.parser()
                .verifyWith(signingKeyProvider.getActiveKey())
                .build()
                .parseSignedClaims(token)
                .getPayload();
    }

    @SuppressWarnings("unchecked")
    public List<String> extractRoles(Claims claims) {
        return (List<String>) claims.get(ROLES_CLAIM, List.class);
    }
}
