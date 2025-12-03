#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>      /* usleep */
#include "nrf24.h"

#define CE_PIN        25
#define SPI_DEVICE    "/dev/spidev0.0"
#define SPI_SPEED     12000000     /* 8 MHz */
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

    uint32_t file_size = 0;
    size_t remaining = 0;
    int got;

    uint8_t fifo_status;
    uint8_t status;

    printf("Waiting for header...\n");

    /* Wait until first payload (header) arrives */
    while (!nrf24_data_ready(&dev)) {
        usleep(100); /* 1 ms */
    }

    got = nrf24_get_payload(&dev, buf, sizeof(buf));
    if (got <= 0) {
        fprintf(stderr, "Failed to read header, got=%d\n", got);
        nrf24_close(&dev);
        fclose(f);
        return 1;
    }

    /* First 4 bytes of the first payload = file size (little-endian) */
    memcpy(&file_size, buf, sizeof(file_size));
    remaining = file_size;

    printf("File size announced by TX: %u bytes\n", file_size);
    printf("Waiting for data...\n");

    nrf24_flush_rx(&dev);

    uint8_t eof = 0;

    nrf24_set_ce(&dev, 1);

    uint32_t N_full_FIFOS = file_size/96;
    uint32_t rest_bytes = file_size%96;

    uint32_t rest_pack = rest_bytes/32 + 1;

    uint32_t rest_size;

    printf("N_FULL_FIFOS:%u",N_full_FIFOS);
    printf("rest_bytes:%u",rest_bytes);
    printf("rest_pack:%u",rest_pack);

    int j = 0;

    int end = 0;

    // Similarly to the TX side, we wait for the fifo to be full and then read exactly
    // 3 entries. This way we control propperly the number of bytes read.
    //while (total_bytes<=file_size) {
    while (j < N_full_FIFOS) {
        nrf24_read_reg(&dev, NRF24_FIFO_STATUS, &fifo_status, 1);
        if (fifo_status & NRF24_FRX_FULL) {
            //nrf24_set_ce(&dev, 0);
            for (int i = 0; i < 3; i++) {
                buf[0] = NRF24_R_RX_PAYLOAD;
                nrf24_command(&dev, buf, 1 + dev.payload_size);
                fwrite(buf + 1, 1, PAYLOAD_SIZE, f);
            }
            total_bytes += 3 * PAYLOAD_SIZE;
            printf("Received %zu bytes (expected %u)\n",
            total_bytes, file_size);
            j++;
            printf("j:%u",j);
            //nrf24_set_ce(&dev, 1);
        }
        // eof = is_all_ff(buf, PAYLOAD_SIZE);
    }

    while (end==0 && rest_bytes>0){ 
        nrf24_read_reg(&dev, NRF24_FIFO_STATUS, &fifo_status, 1);
        if (!(fifo_status & NRF24_FRX_EMPTY)) {
            for (int i = 0; i < rest_pack; i++) {
                buf[0] = NRF24_R_RX_PAYLOAD;
                if (i == rest_pack-1) {
                    rest_size = rest_bytes-(i*PAYLOAD_SIZE);
                }
                else {
                    rest_size = PAYLOAD_SIZE;
                }
                nrf24_command(&dev, buf, 1 + rest_size);
                printf("rest_size:%u",rest_size);
                fwrite(buf + 1, 1, rest_size, f);
            }
            total_bytes += rest_bytes;
            end = 1;
        }
    }
    printf("Received %zu bytes (expected %u)\n",
    total_bytes, file_size);

    nrf24_set_ce(&dev, 0);

    nrf24_close(&dev);
    fclose(f);
    return 0;
}
