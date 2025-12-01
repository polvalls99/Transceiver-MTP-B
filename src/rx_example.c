#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>      /* usleep */
#include "nrf24.h"

#define CE_PIN        25
#define SPI_DEVICE    "/dev/spidev0.0"
#define SPI_SPEED     8000000
#define RF_CHANNEL    76
#define PAYLOAD_SIZE  32

static double now_seconds(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

// XOR wizardry that returns 1 if the whole buffer is 0xFF
int is_all_ff(const void *buf, size_t len) {
    const unsigned char *p = buf;
    size_t i = 0;

    // Align to word boundary for performance
    for (; i < len && ((uintptr_t)&p[i] & (sizeof(size_t)-1)); i++)
        if (p[i] != 0xFF)
            return 0;

    // Compare whole machine words
    size_t ff = ~(size_t)0;
    for (; i + sizeof(size_t) <= len; i += sizeof(size_t))
        if (*(size_t *)(p + i) != ff)
            return 0;

    // Tail
    for (; i < len; i++)
        if (p[i] != 0xFF)
            return 0;

    return 1;
}

uint8_t mega_buff [PAYLOAD_SIZE * 2000];

int main(int argc, char *argv[])
{
    if (argc != 3) {
        fprintf(stderr,
                "Usage: %s <addr5hex> <output_file>\n"
                "Example addr: E7E7E7E7E7\n",
                argv[0]);
        return 1;
    }

    uint8_t addr[5];
    if (sscanf(argv[1], "%2hhX%2hhX%2hhX%2hhX%2hhX",
               &addr[4], &addr[3], &addr[2], &addr[1], &addr[0]) != 5) {
        fprintf(stderr, "Invalid address format\n");
        return 1;
    }

    const char *outname = argv[2];
    FILE *f = fopen(outname, "wb");
    if (!f) {
        perror("fopen");
        return 1;
    }

    nrf24_t dev;
    int rc = nrf24_init(&dev,
                        SPI_DEVICE,
                        CE_PIN,
                        SPI_SPEED,
                        RF24_DR_1MBPS,
                        RF_CHANNEL,
                        PAYLOAD_SIZE,
                        5,
                        RF24_CRC_2BYTES,
                        (uint8_t)' ',
                        RF24_PA_MAX);
    if (rc < 0) {
        fprintf(stderr, "nrf24_init failed: %d\n", rc);
        fclose(f);
        return 1;
    }


    /* RX node listens on pipe 1 with the same address as TX's writing pipe */
    nrf24_open_reading_pipe(&dev, 1, addr, 5);
    nrf24_power_up_rx(&dev);

    /* Debug: print configuration once */
    nrf24_debug_dump(&dev);

    uint8_t buf[PAYLOAD_SIZE + 1];
    size_t total_bytes = 0;
    uint8_t fifo_status;
    uint8_t status;

    // Used for profiling

    printf("Waiting for data...\n");

    nrf24_flush_rx(&dev);

    uint8_t eof = 0;

    nrf24_read_reg(&dev, NRF24_FIFO_STATUS, &fifo_status, 1);

    while (fifo_status & NRF24_FRX_EMPTY) {
        nrf24_read_reg(&dev, NRF24_FIFO_STATUS, &fifo_status, 1);
    }

    nrf24_set_ce(&dev, 1);

    while (!eof) {

        nrf24_read_reg(&dev, NRF24_FIFO_STATUS, &fifo_status, 1);
        status = nrf24_get_status(&dev);

        if (fifo_status & NRF24_FRX_FULL) {
        //if ((status & 0x0E) != 0x0E) {
            nrf24_set_ce(&dev, 0);
            for (int i = 0; i < 3; i++) {
                buf[0] = NRF24_R_RX_PAYLOAD;
                nrf24_command(&dev, buf, 1 + dev.payload_size);
                fwrite(buf + 1, 1, PAYLOAD_SIZE, f);
            }
            total_bytes += 3 * PAYLOAD_SIZE;
            nrf24_set_ce(&dev, 1);
        } else {
          
        }
      // if (nrf24_data_ready(&dev)) {
      //     int got = nrf24_get_payload(&dev, buf, sizeof(buf));
      //     fflush(stdout);
      //     if (got > 0) {
      //         fwrite(buf, 1, (size_t)got, f);
      //         total_bytes += (size_t)got;
      //     }
      // } else {
      //     /* Small sleep to avoid busy-waiting */
      //     usleep(1000); /* 1 ms */
      // }
      // 
      //  /* TODO: add a stopping condition (e.g. known file size or special frame) */
      // 
     // eof = is_all_ff(buf, PAYLOAD_SIZE);
    }

    //fwrite(mega_buff, 1, (total_bytes * PAYLOAD_SIZE), f);

    nrf24_set_ce(&dev, 0);

    nrf24_close(&dev);
    fclose(f);
    return 0;
}
