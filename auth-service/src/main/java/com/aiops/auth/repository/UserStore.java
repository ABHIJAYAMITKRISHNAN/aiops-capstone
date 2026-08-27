package com.aiops.auth.repository;

import com.aiops.auth.model.User;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Hardcoded, in-memory user store.
 *
 * This is an intentional placeholder for Week 1. Per the project roadmap, this will
 * be replaced with a persisted user store in a later week; nothing downstream should
 * assume users are hardcoded.
 */
@Repository
public class UserStore {

    private final Map<String, User> usersByUsername;

    public UserStore() {
        BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();
        this.usersByUsername = Map.of(
                "alice", new User("alice", encoder.encode("alice-pass"), List.of("USER")),
                "bob", new User("bob", encoder.encode("bob-pass"), List.of("USER", "ADMIN"))
        );
    }

    public Optional<User> findByUsername(String username) {
        return Optional.ofNullable(usersByUsername.get(username));
    }
}
