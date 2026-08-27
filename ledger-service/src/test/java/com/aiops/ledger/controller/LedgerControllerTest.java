package com.aiops.ledger.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Transactional
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
class LedgerControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void createAndFetchAccount() throws Exception {
        String createBody = objectMapper.writeValueAsString(new CreateAccountPayload("acct-mvc-1", "USD", "250.00"));

        mockMvc.perform(post("/api/accounts").contentType(APPLICATION_JSON).content(createBody))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.accountId").value("acct-mvc-1"))
                .andExpect(jsonPath("$.balance").value(250.00));

        mockMvc.perform(get("/api/accounts/acct-mvc-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.balance").value(250.00));
    }

    @Test
    void getUnknownAccountReturns404() throws Exception {
        mockMvc.perform(get("/api/accounts/acct-does-not-exist"))
                .andExpect(status().isNotFound());
    }

    @Test
    void debitEndpointReducesBalance() throws Exception {
        mockMvc.perform(post("/api/accounts").contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new CreateAccountPayload("acct-mvc-2", "USD", "100.00"))))
                .andExpect(status().isCreated());

        String debitBody = objectMapper.writeValueAsString(new LedgerOperationPayload("acct-mvc-2", "USD", "40.00"));

        mockMvc.perform(post("/api/ledger/debit").contentType(APPLICATION_JSON).content(debitBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.type").value("DEBIT"))
                .andExpect(jsonPath("$.balanceAfter").value(60.00))
                .andExpect(jsonPath("$.transactionId").isNotEmpty());
    }

    @Test
    void debitBeyondBalanceReturns409() throws Exception {
        mockMvc.perform(post("/api/accounts").contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new CreateAccountPayload("acct-mvc-3", "USD", "5.00"))))
                .andExpect(status().isCreated());

        String debitBody = objectMapper.writeValueAsString(new LedgerOperationPayload("acct-mvc-3", "USD", "50.00"));

        mockMvc.perform(post("/api/ledger/debit").contentType(APPLICATION_JSON).content(debitBody))
                .andExpect(status().isConflict());
    }

    @Test
    void debitOnUnknownAccountReturns404() throws Exception {
        String debitBody = objectMapper.writeValueAsString(new LedgerOperationPayload("acct-nope", "USD", "1.00"));

        mockMvc.perform(post("/api/ledger/debit").contentType(APPLICATION_JSON).content(debitBody))
                .andExpect(status().isNotFound());
    }

    private record CreateAccountPayload(String accountId, String currency, String initialBalance) {
    }

    private record LedgerOperationPayload(String accountId, String currency, String amount) {
    }
}
