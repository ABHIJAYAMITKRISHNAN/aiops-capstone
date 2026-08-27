package com.aiops.auth.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.http.MediaType.APPLICATION_JSON;

@SpringBootTest
@AutoConfigureMockMvc
class AuthControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void loginWithValidCredentialsReturnsToken() throws Exception {
        String body = objectMapper.writeValueAsString(new LoginPayload("alice", "alice-pass"));

        mockMvc.perform(post("/api/auth/login").contentType(APPLICATION_JSON).content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.token").isNotEmpty())
                .andExpect(jsonPath("$.tokenType").value("Bearer"));
    }

    @Test
    void loginWithWrongPasswordReturns401() throws Exception {
        String body = objectMapper.writeValueAsString(new LoginPayload("alice", "wrong-password"));

        mockMvc.perform(post("/api/auth/login").contentType(APPLICATION_JSON).content(body))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").exists());
    }

    @Test
    void loginWithUnknownUserReturns401() throws Exception {
        String body = objectMapper.writeValueAsString(new LoginPayload("nobody", "whatever"));

        mockMvc.perform(post("/api/auth/login").contentType(APPLICATION_JSON).content(body))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void responseCarriesCorrelationIdHeaderEvenWhenNotSupplied() throws Exception {
        String body = objectMapper.writeValueAsString(new LoginPayload("alice", "alice-pass"));

        mockMvc.perform(post("/api/auth/login").contentType(APPLICATION_JSON).content(body))
                .andExpect(header().exists("X-Correlation-Id"));
    }

    @Test
    void responseEchoesSuppliedCorrelationId() throws Exception {
        String body = objectMapper.writeValueAsString(new LoginPayload("alice", "alice-pass"));

        mockMvc.perform(post("/api/auth/login")
                        .contentType(APPLICATION_JSON)
                        .header("X-Correlation-Id", "test-correlation-id-123")
                        .content(body))
                .andExpect(header().string("X-Correlation-Id", "test-correlation-id-123"));
    }

    @Test
    void validateWithFreshlyIssuedTokenReturnsValid() throws Exception {
        String loginBody = objectMapper.writeValueAsString(new LoginPayload("bob", "bob-pass"));
        String response = mockMvc.perform(post("/api/auth/login").contentType(APPLICATION_JSON).content(loginBody))
                .andReturn().getResponse().getContentAsString();
        String token = objectMapper.readTree(response).get("token").asText();

        mockMvc.perform(post("/api/auth/validate")
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new TokenPayload(token))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.valid").value(true))
                .andExpect(jsonPath("$.username").value("bob"))
                .andExpect(jsonPath("$.roles[0]").value("USER"))
                .andExpect(jsonPath("$.roles[1]").value("ADMIN"));
    }

    @Test
    void validateWithGarbageTokenReturnsInvalidNotError() throws Exception {
        mockMvc.perform(post("/api/auth/validate")
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new TokenPayload("garbage-token"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.valid").value(false));
    }

    private record LoginPayload(String username, String password) {
    }

    private record TokenPayload(String token) {
    }
}
