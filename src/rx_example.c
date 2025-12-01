#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>      /* usleep */
#include "nrf24.h"

#define CE_PIN        25
#define SPI_DEVICE    "/dev/spidev0.0"
#define SPI_SPEED     10000000
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
                        RF24_DR_2MBPS,
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


    /* Debug: print configuration once */
    nrf24_debug_dump(&dev);


    /* RX node listens on pipe 1 with the same address as TX's writing pipe */
    nrf24_open_reading_pipe(&dev, 1, addr, 5);
    nrf24_power_up_rx(&dev);

    uint8_t buf[PAYLOAD_SIZE];
    size_t total_bytes = 0;

    printf("Waiting for data...\n");

    while (1) {
        if (nrf24_data_ready(&dev)) {
            int got = nrf24_get_payload(&dev, buf, sizeof(buf));
            fflush(stdout);
            if (got > 0) {
                fwrite(buf, 1, (size_t)got, f);
                total_bytes += (size_t)got;
            }
        } else {
            /* Small sleep to avoid busy-waiting */
            usleep(1000); /* 1 ms */
        }

        /* TODO: add a stopping condition (e.g. known file size or special frame) */
    }

    /* Not reached in this simple example */
    nrf24_close(&dev);
    fclose(f);
    return 0;
}
