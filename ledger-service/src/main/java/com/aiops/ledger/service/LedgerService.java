package com.aiops.ledger.service;

import com.aiops.ledger.exception.AccountAlreadyExistsException;
import com.aiops.ledger.exception.AccountNotFoundException;
import com.aiops.ledger.exception.CurrencyMismatchException;
import com.aiops.ledger.exception.InsufficientFundsException;
import com.aiops.ledger.model.Account;
import com.aiops.ledger.model.LedgerTransaction;
import com.aiops.ledger.model.TransactionType;
import com.aiops.ledger.repository.AccountRepository;
import com.aiops.ledger.repository.LedgerTransactionRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.UUID;

@Service
public class LedgerService {

    private static final Logger log = LoggerFactory.getLogger(LedgerService.class);
    private static final String CORRELATION_ID_MDC_KEY = "correlationId";

    private final AccountRepository accountRepository;
    private final LedgerTransactionRepository ledgerTransactionRepository;

    public LedgerService(AccountRepository accountRepository, LedgerTransactionRepository ledgerTransactionRepository) {
        this.accountRepository = accountRepository;
        this.ledgerTransactionRepository = ledgerTransactionRepository;
    }

    @Transactional
    public Account createAccount(String accountId, String currency, BigDecimal initialBalance) {
        if (accountRepository.findByAccountId(accountId).isPresent()) {
            throw new AccountAlreadyExistsException(accountId);
        }
        Account account = new Account(accountId, currency, initialBalance);
        Account saved = accountRepository.save(account);
        log.info("Created account '{}' with balance {} {}", accountId, initialBalance, currency);
        return saved;
    }

    @Transactional(readOnly = true)
    public Account getAccount(String accountId) {
        return accountRepository.findByAccountId(accountId)
                .orElseThrow(() -> new AccountNotFoundException(accountId));
    }

    @Transactional
    public LedgerTransaction debit(String accountId, String currency, BigDecimal amount) {
        Account account = lockAccount(accountId, currency);
        if (account.getBalance().compareTo(amount) < 0) {
            throw new InsufficientFundsException(accountId);
        }
        account.setBalance(account.getBalance().subtract(amount));
        return recordTransaction(account, TransactionType.DEBIT, amount, currency);
    }

    @Transactional
    public LedgerTransaction credit(String accountId, String currency, BigDecimal amount) {
        Account account = lockAccount(accountId, currency);
        account.setBalance(account.getBalance().add(amount));
        return recordTransaction(account, TransactionType.CREDIT, amount, currency);
    }

    private Account lockAccount(String accountId, String currency) {
        Account account = accountRepository.findByAccountIdForUpdate(accountId)
                .orElseThrow(() -> new AccountNotFoundException(accountId));
        if (!account.getCurrency().equals(currency)) {
            throw new CurrencyMismatchException(accountId, account.getCurrency(), currency);
        }
        return account;
    }

    private LedgerTransaction recordTransaction(Account account, TransactionType type, BigDecimal amount, String currency) {
        String correlationId = MDC.get(CORRELATION_ID_MDC_KEY);
        LedgerTransaction transaction = new LedgerTransaction(
                UUID.randomUUID().toString(), account, type, amount, currency, account.getBalance(), correlationId);
        LedgerTransaction saved = ledgerTransactionRepository.save(transaction);
        log.info("{} of {} {} on account '{}' -> new balance {} (transactionId={})",
                type, amount, currency, account.getAccountId(), account.getBalance(), saved.getTransactionId());
        return saved;
    }
}
