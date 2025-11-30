#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "nrf24.h"

#define CE_PIN        25
#define SPI_DEVICE    "/dev/spidev0.0"
#define SPI_SPEED     8000000 
#define RF_CHANNEL    76
#define PAYLOAD_SIZE  32

static double now_seconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <addr5hex> <file>\n", argv[0]);
        return 1;
    }

    uint8_t addr[5];
    sscanf(argv[1], "%2hhX%2hhX%2hhX%2hhX%2hhX", &addr[4], &addr[3], &addr[2], &addr[1], &addr[0]);

    const char *filename = argv[2];
    FILE *f = fopen(filename, "rb");
    if (!f) { perror("fopen"); return 1; }

    nrf24_t dev;
    // Inicialización igual
    if (nrf24_init(&dev, SPI_DEVICE, CE_PIN, SPI_SPEED, RF24_DR_2MBPS, RF_CHANNEL, PAYLOAD_SIZE, 5, RF24_CRC_2BYTES, ' ', RF24_PA_MAX) < 0) {
        return 1;
    }

    nrf24_open_writing_pipe(&dev, addr, 5);

    uint8_t buf[PAYLOAD_SIZE];
    size_t total_bytes = 0;
    size_t n;
    int success_count = 0;
    int fail_count = 0;

    double t_start = now_seconds();

    while ((n = fread(buf, 1, PAYLOAD_SIZE, f)) > 0) {
        total_bytes += n;
        
        // BUCLE DE STREAMING
        // Intentamos enviar hasta que la FIFO acepte el paquete
        int sent = 0;
        while (!sent) {
            int rc = nrf24_send_fast(&dev, buf, n);
            
            if (rc == 1) {
                // Encolado con éxito
                sent = 1;
                success_count++;
            } else if (rc == 0) {
                // FIFO llena: esperamos un poco (muy poco) para dar tiempo al chip
                // Esto es clave: no esperamos al ACK completo, solo a que se libere un hueco
                usleep(10); 
            } else {
                // Error fatal (MAX_RT, etc)
                fail_count++;
                // Reintentamos enviar el mismo paquete
                usleep(100);
            }
        }
    }

    // Esperar a que se vacíe la cola antes de cerrar
    nrf24_tx_standby(&dev);

    double t_end = now_seconds();
    double elapsed = t_end - t_start;
    double mbps = (total_bytes * 8.0) / (elapsed * 1e6);

    printf("Sent %zu bytes in %.3f s\n", total_bytes, elapsed);
    printf("Throughput: %.3f Mbit/s\n", mbps);
    printf("Packets: %d, Retries/Fails handled: %d\n", success_count, fail_count);

    nrf24_close(&dev);
    fclose(f);
    return 0;
}