#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include "nrf24.h"

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


    /* Debug: print configuration once */
    nrf24_debug_dump(&dev);

    /* TX node uses this address as writing pipe */
    nrf24_open_writing_pipe(&dev, addr, 5);

    uint8_t buf[PAYLOAD_SIZE];
    size_t total_bytes = 0;
    size_t n;

    double t_start = now_seconds();

    printf("AAAAAAAAAA\n");

    while ((n = fread(buf, 1, PAYLOAD_SIZE, f)) > 0) {
        total_bytes += n;

        printf("BBBBBBBBBBBB\n");
        rc = nrf24_send(&dev, buf, n);
        printf("sending bytes: %d", buf);
        if (rc < 0) {
            fprintf(stderr, "send error %d\n", rc);
            break;
        }

        /* Wait for this payload to be transmitted */
        nrf24_wait_until_sent(&dev);
    }

    double t_end = now_seconds();
    double elapsed = t_end - t_start;
    if (elapsed <= 0.0) elapsed = 1e-9;

    double user_thr_mbps = (total_bytes * 8.0) / (elapsed * 1e6);

    printf("Sent %zu bytes in %.3f s => user throughput: %.3f Mbit/s\n",
           total_bytes, elapsed, user_thr_mbps);

    nrf24_close(&dev);
    fclose(f);
    return 0;
}
