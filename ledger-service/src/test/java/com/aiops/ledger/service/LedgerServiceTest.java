package com.aiops.ledger.service;

import com.aiops.ledger.exception.AccountAlreadyExistsException;
import com.aiops.ledger.exception.AccountNotFoundException;
import com.aiops.ledger.exception.CurrencyMismatchException;
import com.aiops.ledger.exception.InsufficientFundsException;
import com.aiops.ledger.model.Account;
import com.aiops.ledger.model.LedgerTransaction;
import com.aiops.ledger.model.TransactionType;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest
@Transactional
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
class LedgerServiceTest {

    @Autowired
    private LedgerService ledgerService;

    @Test
    void createsAccountWithInitialBalance() {
        Account account = ledgerService.createAccount("acct-create-1", "USD", new BigDecimal("100.00"));

        assertThat(account.getAccountId()).isEqualTo("acct-create-1");
        assertThat(account.getBalance()).isEqualByComparingTo("100.00");
    }

    @Test
    void rejectsDuplicateAccountId() {
        ledgerService.createAccount("acct-dup", "USD", BigDecimal.TEN);

        assertThatThrownBy(() -> ledgerService.createAccount("acct-dup", "USD", BigDecimal.ONE))
                .isInstanceOf(AccountAlreadyExistsException.class);
    }

    @Test
    void debitReducesBalanceAndRecordsTransaction() {
        ledgerService.createAccount("acct-debit-1", "USD", new BigDecimal("100.00"));

        LedgerTransaction tx = ledgerService.debit("acct-debit-1", "USD", new BigDecimal("30.00"));

        assertThat(tx.getType()).isEqualTo(TransactionType.DEBIT);
        assertThat(tx.getBalanceAfter()).isEqualByComparingTo("70.00");
        assertThat(ledgerService.getAccount("acct-debit-1").getBalance()).isEqualByComparingTo("70.00");
    }

    @Test
    void creditIncreasesBalanceAndRecordsTransaction() {
        ledgerService.createAccount("acct-credit-1", "USD", new BigDecimal("100.00"));

        LedgerTransaction tx = ledgerService.credit("acct-credit-1", "USD", new BigDecimal("50.00"));

        assertThat(tx.getType()).isEqualTo(TransactionType.CREDIT);
        assertThat(tx.getBalanceAfter()).isEqualByComparingTo("150.00");
    }

    @Test
    void debitRejectsWhenBalanceInsufficient() {
        ledgerService.createAccount("acct-insufficient-1", "USD", new BigDecimal("10.00"));

        assertThatThrownBy(() -> ledgerService.debit("acct-insufficient-1", "USD", new BigDecimal("20.00")))
                .isInstanceOf(InsufficientFundsException.class);

        // balance must be unchanged after a rejected debit
        assertThat(ledgerService.getAccount("acct-insufficient-1").getBalance()).isEqualByComparingTo("10.00");
    }

    @Test
    void debitRejectsUnknownAccount() {
        assertThatThrownBy(() -> ledgerService.debit("acct-does-not-exist", "USD", BigDecimal.ONE))
                .isInstanceOf(AccountNotFoundException.class);
    }

    @Test
    void debitRejectsCurrencyMismatch() {
        ledgerService.createAccount("acct-currency-1", "USD", new BigDecimal("100.00"));

        assertThatThrownBy(() -> ledgerService.debit("acct-currency-1", "EUR", new BigDecimal("10.00")))
                .isInstanceOf(CurrencyMismatchException.class);
    }
}
