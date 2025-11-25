#ifndef NRF24_H
#define NRF24_H

#include <stdint.h>
#include <stddef.h>

/* Power Amplifier levels */
typedef enum {
    RF24_PA_MIN  = 0,
    RF24_PA_LOW  = 1,
    RF24_PA_HIGH = 2,
    RF24_PA_MAX  = 3
} rf24_pa_t;

/* Data rate selection */
typedef enum {
    RF24_DR_1MBPS   = 0,
    RF24_DR_2MBPS   = 1,
    RF24_DR_250KBPS = 2
} rf24_data_rate_t;

/* CRC configuration */
typedef enum {
    RF24_CRC_DISABLED = 0,
    RF24_CRC_1BYTE    = 1,
    RF24_CRC_2BYTES   = 2
} rf24_crc_t;

/* NRF24 device context */
typedef struct {
    int      spi_fd;        /* File descriptor for /dev/spidevX.Y */
    uint32_t spi_speed;     /* SPI speed in Hz */

    unsigned ce_pin;        /* GPIO used as CE */

    uint8_t  payload_size;  /* Fixed payload size in bytes (1..32) */
    uint8_t  address_width; /* Address width in bytes (3..5) */
    uint8_t  padding;       /* Padding byte for short frames */
    uint8_t  power_tx;      /* 1 if currently in TX mode */

} nrf24_t;

/* ---- Public API ---- */

/* Initialize NRF24 device.
 * spi_device example: "/dev/spidev0.0"
 * Returns 0 on success, negative value on error.
 */
int nrf24_init(nrf24_t *dev,
               const char *spi_device,
               unsigned ce_pin,
               uint32_t spi_speed,
               rf24_data_rate_t data_rate,
               uint8_t channel,
               uint8_t payload_size,
               uint8_t address_width,
               rf24_crc_t crc_bytes,
               uint8_t pad,
               rf24_pa_t pa_level);

/* Close SPI handle. Does NOT touch GPIO sysfs. */
void nrf24_close(nrf24_t *dev);

/* Basic configuration setters */
int nrf24_set_channel(nrf24_t *dev, uint8_t channel);
int nrf24_set_retransmission(nrf24_t *dev, uint8_t delay, uint8_t retries);
int nrf24_set_data_rate(nrf24_t *dev, rf24_data_rate_t rate);
int nrf24_set_pa_level(nrf24_t *dev, rf24_pa_t level);
int nrf24_set_crc_bytes(nrf24_t *dev, rf24_crc_t crc_bytes);

/* Pipe configuration.
 * addr length MUST match dev->address_width.
 */
int nrf24_open_writing_pipe(nrf24_t *dev, const uint8_t *addr, size_t len);
/* Supports pipes 0..5 (0 and 1 use full address). */
int nrf24_open_reading_pipe(nrf24_t *dev, uint8_t pipe,
                            const uint8_t *addr, size_t len);

/* TX API */
int  nrf24_send(nrf24_t *dev, const uint8_t *data, size_t len);
int  nrf24_is_sending(nrf24_t *dev);
/* Simple wait, no timeout. Returns 0 on success. */
int  nrf24_wait_until_sent(nrf24_t *dev);

/* RX API */
int  nrf24_data_ready(nrf24_t *dev);
/* len MUST be >= dev->payload_size.
 * Returns payload_size on success, negative on error.
 */
int  nrf24_get_payload(nrf24_t *dev, uint8_t *data, size_t len);

/* Power state control */
void nrf24_power_up_rx(nrf24_t *dev);
void nrf24_power_up_tx(nrf24_t *dev);
void nrf24_power_down(nrf24_t *dev);

/* FIFO helpers */
void nrf24_flush_rx(nrf24_t *dev);
void nrf24_flush_tx(nrf24_t *dev);

/* STATUS register */
uint8_t nrf24_get_status(nrf24_t *dev);

#endif /* NRF24_H */
