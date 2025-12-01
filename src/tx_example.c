#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>
#include <string.h>
#include <time.h>
#include "nrf24.h"
#include "regmap.h"

#define CE_PIN        25          /* Adjust to your CE GPIO pin */
#define SPI_DEVICE    "/dev/spidev0.0"
#define SPI_SPEED     8000000     /* 8 MHz */
#define RF_CHANNEL    76
#define PAYLOAD_SIZE  32

static double now_seconds(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

int main(int argc, char *argv[])
{
    if (argc != 3) {
        fprintf(stderr,
                "Usage: %s <addr5hex> <file>\n"
                "Example addr: E7E7E7E7E7\n",
                argv[0]);
        return 1;
    }

    /* Parse address as 5-byte hex string (same style as your Python code) */
    uint8_t addr[5];
    if (sscanf(argv[1], "%2hhX%2hhX%2hhX%2hhX%2hhX",
               &addr[4], &addr[3], &addr[2], &addr[1], &addr[0]) != 5) {
        fprintf(stderr, "Invalid address format\n");
        return 1;
    }

    const char *filename = argv[2];
    FILE *f = fopen(filename, "rb");
    if (!f) {
        perror("fopen");
        return 1;
    }

    nrf24_t dev;
    int rc = nrf24_init(&dev,
                        SPI_DEVICE,
                        CE_PIN,
                        SPI_SPEED,
                        RF24_DR_2MBPS,
                        RF_CHANNEL,
                        PAYLOAD_SIZE,
                        5,
                        RF24_CRC_2BYTES,
                        (uint8_t)' ',    /* padding byte */
                        RF24_PA_MAX);
    if (rc < 0) {
        fprintf(stderr, "nrf24_init failed: %d\n", rc);
        fclose(f);
        return 1;
    }

    /* TX node uses this address as writing pipe */
    nrf24_open_writing_pipe(&dev, addr, 5);
    nrf24_power_up_tx(&dev);

    /* Debug: print configuration once */
    nrf24_debug_dump(&dev);

    uint8_t buf[PAYLOAD_SIZE + 1];
    uint8_t fifo_cnt = 0; // How many payloads are in the TX FIFO
    size_t total_bytes = 0;
    size_t n = 1;
    uint8_t fifo_status;
    uint8_t status;
    uint8_t config;

    double t_start = now_seconds();

    //buf[0] = NRF24_W_TX_PAYLOAD; // Byte 0 is hardcoded to the command

    // Put the CE down, only set back to 1 once we have finished
    //nrf24_set_ce(&dev, 1);

    // We store the read starting in the second index because the first byte
    // will hold the command we are sending to the nrf24.
    // while ((n = fread(buf + 1, 1, PAYLOAD_SIZE, f)) > 0) {
    //     total_bytes += n;
    // 
    //     buf[0] = NRF24_W_TX_PAYLOAD; // Byte 0 is hardcoded to the command
    // 
    //     // The FIFO holds 3 full payloads, so we queue 3 at a time
    //     // and then wait for it to be empty.
    //     nrf24_read_reg(&dev, NRF24_FIFO_STATUS, &fifo_status, 1);
    // 
    //     if (!(fifo_status & NRF24_FTX_FULL)) {
    //         nrf24_command(&dev, buf, 1 + dev.payload_size);
    //     } else {
    //         // Fifo is full, we are waiting
    //         while ((fifo_status & NRF24_FTX_FULL)) {
    //             nrf24_read_reg(&dev, NRF24_FIFO_STATUS, &fifo_status, 1);
    //         }
    //         usleep(20000);
    //     }
    // }
    while (n > 0) {
        nrf24_read_reg(&dev, NRF24_FIFO_STATUS, &fifo_status, 1);
        //printf("%x ", fifo_status);

        // Wait for the FIFO to be empty
        while (!(fifo_status & NRF24_FTX_EMPTY)) nrf24_read_reg(&dev, NRF24_FIFO_STATUS, &fifo_status, 1);

        // Send 3 payloads
        for (int i = 0; i < 3; i++) {
            buf[0] = NRF24_W_TX_PAYLOAD; // Byte 0 is hardcoded to the command
            if ((n = fread(buf + 1, 1, PAYLOAD_SIZE, f)) <= 0) break;
            total_bytes += n;
            nrf24_command(&dev, buf, 1 + dev.payload_size);
        }
    }

    // Send a payload of 32 1s to stop the transmission
    nrf24_read_reg(&dev, NRF24_FIFO_STATUS, &fifo_status, 1);
    while ((fifo_status & NRF24_FTX_FULL)) {
        nrf24_read_reg(&dev, NRF24_FIFO_STATUS, &fifo_status, 1);
    }
    memset(buf + 1, 0xFF, PAYLOAD_SIZE);
    nrf24_command(&dev, buf, 1 + dev.payload_size);

    double t_end = now_seconds();
    double elapsed = t_end - t_start;
    if (elapsed <= 0.0) elapsed = 1e-9;

    // Put the CE back up
    nrf24_set_ce(&dev, 0);

    double user_thr_mbps = (total_bytes * 8.0) / (elapsed * 1e6);

    printf("Sent %zu bytes in %.3f s => user throughput: %.3f Mbit/s\n",
           total_bytes, elapsed, user_thr_mbps);

    sleep(2);
    nrf24_close(&dev);
    fclose(f);
    return 0;
}
