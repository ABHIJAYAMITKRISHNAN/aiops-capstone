package com.aiops.ledger.repository;

import com.aiops.ledger.model.Account;
import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;

import java.util.Optional;

public interface AccountRepository extends JpaRepository<Account, Long> {

    Optional<Account> findByAccountId(String accountId);

    /**
     * Locks the account row for the duration of the caller's transaction so concurrent
     * debits/credits against the same account serialize instead of racing on the balance.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select a from Account a where a.accountId = :accountId")
    Optional<Account> findByAccountIdForUpdate(String accountId);
}
