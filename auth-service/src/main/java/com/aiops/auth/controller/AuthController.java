package com.aiops.auth.controller;

import com.aiops.auth.dto.LoginRequest;
import com.aiops.auth.dto.LoginResponse;
import com.aiops.auth.dto.ValidateRequest;
import com.aiops.auth.dto.ValidateResponse;
import com.aiops.auth.exception.InvalidCredentialsException;
import com.aiops.auth.model.User;
import com.aiops.auth.repository.UserStore;
import com.aiops.auth.security.JwtService;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import jakarta.validation.Valid;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private static final Logger log = LoggerFactory.getLogger(AuthController.class);

    private final UserStore userStore;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final long expirationMs;

    public AuthController(UserStore userStore,
                           PasswordEncoder passwordEncoder,
                           JwtService jwtService,
                           @Value("${app.jwt.expiration-ms}") long expirationMs) {
        this.userStore = userStore;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.expirationMs = expirationMs;
    }

    @PostMapping("/login")
    public LoginResponse login(@Valid @RequestBody LoginRequest request) {
        User user = userStore.findByUsername(request.username())
                .filter(u -> passwordEncoder.matches(request.password(), u.passwordHash()))
                .orElseThrow(InvalidCredentialsException::new);

        String token = jwtService.generateToken(user.username(), user.roles());
        log.info("User '{}' authenticated successfully", user.username());
        return new LoginResponse(token, expirationMs);
    }

    @PostMapping("/validate")
    public ValidateResponse validate(@Valid @RequestBody ValidateRequest request) {
        try {
            Claims claims = jwtService.parseAndValidate(request.token());
            log.info("Token validated successfully for user '{}'", claims.getSubject());
            return ValidateResponse.valid(claims.getSubject(), jwtService.extractRoles(claims));
        } catch (JwtException e) {
            log.info("Token validation failed: {}", e.getMessage());
            return ValidateResponse.invalid(e.getMessage());
        }
    }
}
