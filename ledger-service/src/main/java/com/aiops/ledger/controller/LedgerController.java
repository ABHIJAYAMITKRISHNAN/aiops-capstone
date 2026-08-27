package com.aiops.ledger.controller;

import com.aiops.ledger.dto.LedgerOperationRequest;
import com.aiops.ledger.dto.LedgerTransactionResponse;
import com.aiops.ledger.service.LedgerService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/ledger")
public class LedgerController {

    private final LedgerService ledgerService;

    public LedgerController(LedgerService ledgerService) {
        this.ledgerService = ledgerService;
    }

    @PostMapping("/debit")
    public LedgerTransactionResponse debit(@Valid @RequestBody LedgerOperationRequest request) {
        return LedgerTransactionResponse.from(
                ledgerService.debit(request.accountId(), request.currency(), request.amount()));
    }

    @PostMapping("/credit")
    public LedgerTransactionResponse credit(@Valid @RequestBody LedgerOperationRequest request) {
        return LedgerTransactionResponse.from(
                ledgerService.credit(request.accountId(), request.currency(), request.amount()));
    }
}
