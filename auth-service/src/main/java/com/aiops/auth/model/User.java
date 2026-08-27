package com.aiops.auth.model;

import java.util.List;

/**
 * @param passwordHash BCrypt hash, never the raw password.
 */
public record User(String username, String passwordHash, List<String> roles) {
}
