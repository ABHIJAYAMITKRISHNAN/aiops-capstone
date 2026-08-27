package com.aiops.payment;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

// @EnableScheduling is required by the MEMORY_LEAK fault-injection mechanism
// (fault.MemoryLeakFaultService's @Scheduled allocation loop); it is a no-op when that fault
// is inactive (the default).
@EnableScheduling
@SpringBootApplication
public class PaymentServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(PaymentServiceApplication.class, args);
    }
}
