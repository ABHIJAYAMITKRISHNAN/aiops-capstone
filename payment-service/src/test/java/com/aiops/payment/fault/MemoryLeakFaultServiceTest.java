package com.aiops.payment.fault;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class MemoryLeakFaultServiceTest {

    private static final int CHUNK_SIZE = 1000;
    private static final long MAX_TOTAL = 3500; // 3.5 chunks worth, to verify the cap stops growth mid-tick

    private final MemoryLeakFaultService service = new MemoryLeakFaultService(CHUNK_SIZE, MAX_TOTAL);

    @Test
    void disabledByDefaultAndAllocatesNothingUntilInjected() {
        service.allocateIfEnabled();

        assertThat(service.isEnabled()).isFalse();
        assertThat(service.getRetainedBytes()).isZero();
        assertThat(service.getRetainedChunkCount()).isZero();
    }

    @Test
    void injectEnablesAllocationOnEachTick() {
        service.inject();

        service.allocateIfEnabled();
        service.allocateIfEnabled();

        assertThat(service.isEnabled()).isTrue();
        assertThat(service.getRetainedChunkCount()).isEqualTo(2);
        assertThat(service.getRetainedBytes()).isEqualTo(2L * CHUNK_SIZE);
    }

    @Test
    void allocationStopsOnceMaxTotalBytesReached() {
        service.inject();

        for (int i = 0; i < 10; i++) {
            service.allocateIfEnabled();
        }

        assertThat(service.getRetainedBytes()).isLessThanOrEqualTo(MAX_TOTAL);
        assertThat(service.isEnabled()).isTrue(); // still "on", just capped - not silently disabled
    }

    @Test
    void resetClearsRetainedMemoryAndStopsAllocation() {
        service.inject();
        service.allocateIfEnabled();
        service.allocateIfEnabled();

        service.reset();

        assertThat(service.isEnabled()).isFalse();
        assertThat(service.getRetainedBytes()).isZero();
        assertThat(service.getRetainedChunkCount()).isZero();

        // a tick after reset must not resume allocation
        service.allocateIfEnabled();
        assertThat(service.getRetainedBytes()).isZero();
    }
}
