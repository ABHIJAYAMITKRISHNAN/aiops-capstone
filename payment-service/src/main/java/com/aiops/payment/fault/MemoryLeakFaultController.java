package com.aiops.payment.fault;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * INTENTIONAL FAULT-INJECTION ENDPOINTS for the MEMORY_LEAK controlled experiment. Not part of
 * the normal payment-service API contract. See MemoryLeakFaultService for the mechanism and its
 * safety cap.
 */
@RestController
public class MemoryLeakFaultController {

    private final MemoryLeakFaultService memoryLeakFaultService;

    public MemoryLeakFaultController(MemoryLeakFaultService memoryLeakFaultService) {
        this.memoryLeakFaultService = memoryLeakFaultService;
    }

    @PostMapping("/inject-memory-leak")
    public FaultStatus inject() {
        memoryLeakFaultService.inject();
        return status("Memory leak fault injected.");
    }

    @PostMapping("/reset-memory-leak")
    public FaultStatus reset() {
        memoryLeakFaultService.reset();
        return status("Memory leak fault reset.");
    }

    private FaultStatus status(String message) {
        return new FaultStatus(memoryLeakFaultService.isEnabled(), memoryLeakFaultService.getRetainedBytes(),
                memoryLeakFaultService.getRetainedChunkCount(), message);
    }

    public record FaultStatus(boolean faultActive, long retainedBytes, int retainedChunkCount, String message) {
    }
}
