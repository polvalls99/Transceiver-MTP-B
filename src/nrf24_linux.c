#include "nrf24.h"
#include <dirent.h>   /* DIR, opendir, readdir */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <limits.h>   /* PATH_MAX */
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>
#include "regmap.h"

/* ---- GPIO (sysfs) helpers ---- */

/* Read the base offset from the first gpiochip found in /sys/class/gpio.
 * This base is added to the BCM pin number to get the global GPIO number.
 */
static int gpio_get_base(void)
{
    DIR *d = opendir("/sys/class/gpio");
    if (!d) {
        /* Fallback to 0 if directory cannot be opened. */
        return 0;
    }

    struct dirent *de;
    int base = 0;

    while ((de = readdir(d)) != NULL) {
        if (strncmp(de->d_name, "gpiochip", 8) == 0) {
            char path[PATH_MAX];
            int n = snprintf(path, sizeof(path),
                             "/sys/class/gpio/%s/base", de->d_name);
            /* If the path would be truncated, skip this entry */
            if (n <= 0 || n >= (int)sizeof(path)) {
                continue;
            }

            FILE *f = fopen(path, "r");
            if (f) {
                int b;
                if (fscanf(f, "%d", &b) == 1) {
                    base = b;
                    fclose(f);
                    break; /* Use the first gpiochip found */
                }
                fclose(f);
            }
        }
    }

    closedir(d);
    return base;
}


/* Export a GPIO line using sysfs interface (global line number). */
static int gpio_export(int line)
{
    FILE *f = fopen("/sys/class/gpio/export", "w");
    if (!f) {
        if (errno == EBUSY) {
            /* GPIO is already exported, this is fine. */
            return 0;
        }
        perror("gpio export");
        return -1;
    }
    fprintf(f, "%d\n", line);
    fclose(f);
    return 0;
}

/* Write logical value 0 or 1 to GPIO line (global number). */
static int gpio_write_line(int line, int value)
{
    char path[64];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%d/value", line);
    FILE *f = fopen(path, "w");
    if (!f) {
        perror("gpio value");
        return -1;
    }
    fprintf(f, "%d\n", value ? 1 : 0);
    fclose(f);
    return 0;
}

/* Initialize CE pin for output and drive low.
 * The input ce_pin_bcm is the BCM GPIO number (e.g. 25).
 * Internally we convert it to the global line number: line = base + ce_pin_bcm.
 */
static int nrf24_ce_init(nrf24_t *dev, int ce_pin_bcm)
{
    int base = gpio_get_base();
    int line = base + ce_pin_bcm;

    dev->ce_pin = (unsigned)line;

    if (gpio_export(line) < 0) {
        return -1;
    }

    /* Wait for the kernel to create the gpio directory */
    char path[64];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%d/direction", line);

    FILE *f = NULL;
    int tries;
    for (tries = 0; tries < 100; ++tries) {
        f = fopen(path, "w");
        if (f) {
            break;
        }
        if (errno == ENOENT) {
            /* Directory not ready yet, wait 10 ms and retry */
            usleep(10000);
            continue;
        }
        /* Any other error is fatal */
        perror("gpio direction");
        return -1;
    }

    if (!f) {
        fprintf(stderr, "gpio direction: timeout waiting for %s\n", path);
        return -1;
    }

    fprintf(f, "out\n");
    fclose(f);

    /* Drive CE low initially */
    return gpio_write_line(line, 0);
}

/* Set CE pin high or low. dev->ce_pin stores the global line number. */
void nrf24_set_ce(nrf24_t *dev, int level)
{
    gpio_write_line((int)dev->ce_pin, level ? 1 : 0);
}

static void nrf24_unset_ce(nrf24_t *dev)
{
    nrf24_set_ce(dev, 0);
}

static void nrf24_set_ce_high(nrf24_t *dev)
{
    nrf24_set_ce(dev, 1);
}


/* ---- SPI (spidev) helpers ---- */

/* Initialize SPI device using Linux spidev. */
static int nrf24_spi_init(nrf24_t *dev, const char *spi_device, uint32_t speed_hz)
{
    int fd = open(spi_device, O_RDWR);
    if (fd < 0) {
        perror("open spidev");
        return -1;
    }

    uint8_t mode = 0; /* SPI mode 0: CPOL=0, CPHA=0 */
    uint8_t bits = 8;

    if (ioctl(fd, SPI_IOC_WR_MODE, &mode) < 0) {
        perror("SPI_IOC_WR_MODE");
        close(fd);
        return -1;
    }
    if (ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits) < 0) {
        perror("SPI_IOC_WR_BITS_PER_WORD");
        close(fd);
        return -1;
    }
    if (ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed_hz) < 0) {
        perror("SPI_IOC_WR_MAX_SPEED_HZ");
        close(fd);
        return -1;
    }

    dev->spi_fd    = fd;
    dev->spi_speed = speed_hz;
    return 0;
}

/* SPI full-duplex transfer using spidev. */
static int nrf24_xfer(nrf24_t *dev, uint8_t *data, unsigned len)
{
    struct spi_ioc_transfer tr;
    memset(&tr, 0, sizeof(tr));

    tr.tx_buf        = (unsigned long)data;
    tr.rx_buf        = (unsigned long)data;
    tr.len           = len;
    tr.speed_hz      = dev->spi_speed;
    tr.bits_per_word = 8;

    int ret = ioctl(dev->spi_fd, SPI_IOC_MESSAGE(1), &tr);
    if (ret < 0) {
        perror("SPI_IOC_MESSAGE");
    }
    return ret;
}

static void nrf24_spi_close(nrf24_t *dev)
{
    if (dev->spi_fd >= 0) {
        close(dev->spi_fd);
        dev->spi_fd = -1;
    }
}

/* ---- Register access helpers ---- */

int nrf24_command(nrf24_t *dev, uint8_t *buf, unsigned len)
{
    return nrf24_xfer(dev, buf, len);
}

int nrf24_read_reg(nrf24_t *dev, uint8_t reg, uint8_t *dst, unsigned len)
{
    uint8_t buf[1 + 32];
    if (len > 32) return -1;

    buf[0] = NRF24_R_REGISTER | (reg & 0x1F);
    memset(buf + 1, 0, len);

    int status = nrf24_xfer(dev, buf, 1 + len);
    if (status >= 0) {
        memcpy(dst, buf + 1, len);
    }
    return status;
}

static int nrf24_write_reg(nrf24_t *dev, uint8_t reg, const uint8_t *src, unsigned len)
{
    uint8_t buf[1 + 32];
    if (len > 32) return -1;

    buf[0] = NRF24_W_REGISTER | (reg & 0x1F);
    memcpy(buf + 1, src, len);

    return nrf24_xfer(dev, buf, 1 + len);
}

/* ---- Public functions ---- */

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
               rf24_pa_t pa_level)
{
    if (!dev) return -1;

    if (payload_size < 1 || payload_size > 32) return -2;
    if (address_width < 3 || address_width > 5) return -3;
    if (channel > 125) return -4;

    memset(dev, 0, sizeof(*dev));
    dev->spi_fd        = -1;
    dev->spi_speed     = spi_speed;
    dev->ce_pin        = ce_pin;
    dev->payload_size  = payload_size;
    dev->address_width = address_width;
    dev->padding       = pad;
    dev->power_tx      = 0;

    // Initialize SPI device
    if (nrf24_spi_init(dev, spi_device, spi_speed) < 0) {
        return -5;
    }
    if (nrf24_ce_init(dev, ce_pin) < 0) {
        nrf24_spi_close(dev);
        return -6;
    }

    /* Set RF channel */
    nrf24_set_channel(dev, channel);

    /* Set retransmission: delay=1 (500us), retries=15 (max) */
    nrf24_set_retransmission(dev, 1, 15);

    /* Set fixed payload size for pipes 0 and 1 */
    {
        uint8_t size = dev->payload_size;
        nrf24_write_reg(dev, NRF24_RX_PW_P0, &size, 1);
        nrf24_write_reg(dev, NRF24_RX_PW_P1, &size, 1);
    }

    /* Set address width */
    {
        uint8_t aw = (uint8_t)(dev->address_width - 2);
        nrf24_write_reg(dev, NRF24_SETUP_AW, &aw, 1);
    }

    /* CRC configuration */
    nrf24_set_crc_bytes(dev, crc_bytes);

    /* Data rate and PA level */
    nrf24_set_data_rate(dev, data_rate);
    nrf24_set_pa_level(dev, pa_level);

    /* Power down, flush FIFOs, then power up in RX mode */
    nrf24_power_down(dev);
    nrf24_flush_rx(dev);
    nrf24_flush_tx(dev);
    nrf24_power_up_rx(dev);

    return 0;
}

void nrf24_close(nrf24_t *dev)
{
    if (!dev) return;
    nrf24_spi_close(dev);
}

/* Set RF channel (0..125, corresponds to 2400+ch MHz) */
int nrf24_set_channel(nrf24_t *dev, uint8_t channel)
{
    if (!dev) return -1;
    if (channel > 125) return -2;

    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_RF_CH, &channel, 1);
    nrf24_set_ce_high(dev);
    return 0;
}

int nrf24_set_retransmission(nrf24_t *dev, uint8_t delay, uint8_t retries)
{
    if (!dev) return -1;
    if (delay > 15 || retries > 15) return -2;

    uint8_t val = (uint8_t)((delay << 4) | (retries & 0x0F));
    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_SETUP_RETR, &val, 1);
    nrf24_set_ce_high(dev);
    return 0;
}

int nrf24_set_data_rate(nrf24_t *dev, rf24_data_rate_t rate)
{
    if (!dev) return -1;

    uint8_t rf_setup;
    nrf24_read_reg(dev, NRF24_RF_SETUP, &rf_setup, 1);

    /* Clear DR bit */
    rf_setup &= ~NRF24_RF_DR;

    rf_setup = rate ? rf_setup | RF24_DR_2MBPS : rf_setup | RF24_DR_1MBPS;

    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_RF_SETUP, &rf_setup, 1);
    nrf24_set_ce_high(dev);

    return 0;
}

int nrf24_set_pa_level(nrf24_t *dev, rf24_pa_t level)
{
    if (!dev) return -1;

    uint8_t rf_setup;
    nrf24_read_reg(dev, NRF24_RF_SETUP, &rf_setup, 1);

    /* Clear power bits */
    rf_setup &= ~(NRF24_RF_PWR_LOW | NRF24_RF_PWR_HIGH);

    /* Level mapping similar to datasheet:
     *  MIN -> -18 dBm, LOW -> -12 dBm, HIGH -> -6 dBm, MAX -> 0 dBm
     */
    switch (level) {
        case RF24_PA_MIN:
            /* 00 -> -18 dBm */
            break;
        case RF24_PA_LOW:
            rf_setup |= NRF24_RF_PWR_LOW;
            break;
        case RF24_PA_HIGH:
            rf_setup |= NRF24_RF_PWR_HIGH;
            break;
        case RF24_PA_MAX:
        default:
            rf_setup |= (NRF24_RF_PWR_LOW | NRF24_RF_PWR_HIGH);
            break;
    }

    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_RF_SETUP, &rf_setup, 1);
    nrf24_set_ce_high(dev);

    return 0;
}

int nrf24_set_crc_bytes(nrf24_t *dev, rf24_crc_t crc_bytes)
{
    if (!dev) return -1;

    uint8_t config;
    nrf24_read_reg(dev, NRF24_CONFIG, &config, 1);

    nrf24_unset_ce(dev);

    if (crc_bytes == RF24_CRC_DISABLED) {
        /* Disable CRC */
        config &= ~NRF24_EN_CRC;
    } else {
        /* Enable CRC */
        config |= NRF24_EN_CRC;
        if (crc_bytes == RF24_CRC_2BYTES) {
            config |= NRF24_CRCO;
        } else {
            config &= ~NRF24_CRCO;
        }
    }

    nrf24_write_reg(dev, NRF24_CONFIG, &config, 1);
    nrf24_set_ce_high(dev);

    return 0;
}

/* Open writing pipe (TX_ADDR and RX_ADDR_P0).
 * addr length MUST be dev->address_width.
 */
int nrf24_open_writing_pipe(nrf24_t *dev, const uint8_t *addr, size_t len)
{
    if (!dev || !addr) return -1;
    if (len != dev->address_width) return -2;

    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_TX_ADDR, addr, (unsigned)len);
    nrf24_write_reg(dev, NRF24_RX_ADDR_P0, addr, (unsigned)len);

    /* Enable auto-ack on pipe 0 and enable reception on pipe 0 */
    uint8_t en_aa, en_rx;
    nrf24_read_reg(dev, NRF24_EN_AA, &en_aa, 1);
    nrf24_read_reg(dev, NRF24_EN_RXADDR, &en_rx, 1);

    en_aa |= (1 << 0);   /* P0 */
    en_rx |= (1 << 0);   /* P0 */

    nrf24_write_reg(dev, NRF24_EN_AA, &en_aa, 1);
    nrf24_write_reg(dev, NRF24_EN_RXADDR, &en_rx, 1);

    /* Set fixed payload size for pipe 0 */
    uint8_t size = dev->payload_size;
    nrf24_write_reg(dev, NRF24_RX_PW_P0, &size, 1);

    nrf24_set_ce_high(dev);

    return 0;
}

/* Open reading pipe (supports 0..5).
 * addr length MUST be dev->address_width.
 */
int nrf24_open_reading_pipe(nrf24_t *dev, uint8_t pipe,
                            const uint8_t *addr, size_t len)
{
    if (!dev || !addr) return -1;
    if (pipe > 5) return -2;
    if (len != dev->address_width) return -3;

    nrf24_unset_ce(dev);

    if (pipe == 0 || pipe == 1) {
        /* Full address for pipe 0 and 1 */
        uint8_t reg = (pipe == 0) ? NRF24_RX_ADDR_P0 : NRF24_RX_ADDR_P1;
        nrf24_write_reg(dev, reg, addr, (unsigned)len);
    } else {
        /* Pipes 2..5 share the high bytes with pipe 1 and only LSB differs.
         * For simplicity we only write the LSB from addr[0].
         */
        uint8_t lsb = addr[0];
        uint8_t reg = NRF24_RX_ADDR_P0 + pipe;
        nrf24_write_reg(dev, reg, &lsb, 1);
    }

    /* Enable auto-ack and RX for this pipe */
    uint8_t en_aa, en_rx;
    nrf24_read_reg(dev, NRF24_EN_AA, &en_aa, 1);
    nrf24_read_reg(dev, NRF24_EN_RXADDR, &en_rx, 1);

    en_aa |= (1 << pipe);
    en_rx |= (1 << pipe);

    nrf24_write_reg(dev, NRF24_EN_AA, &en_aa, 1);
    nrf24_write_reg(dev, NRF24_EN_RXADDR, &en_rx, 1);

    /* Fixed payload size */
    uint8_t size = dev->payload_size;
    uint8_t reg_pw = NRF24_RX_PW_P0 + pipe;
    nrf24_write_reg(dev, reg_pw, &size, 1);

    nrf24_set_ce_high(dev);
    return 0;
}

/* Power control functions */

void nrf24_power_up_tx(nrf24_t *dev)
{
    if (!dev) return;

    dev->power_tx = 1;
    uint8_t config;
    nrf24_read_reg(dev, NRF24_CONFIG, &config, 1);

    config &= ~NRF24_PRIM_RX;             /* Disable RX */
    config |= NRF24_PWR_UP;               /* Ensure power up */

    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_CONFIG, &config, 1);

    /* Clear IRQ flags in STATUS */
    uint8_t status = NRF24_RX_DR | NRF24_TX_DS | NRF24_MAX_RT;
    nrf24_write_reg(dev, NRF24_STATUS, &status, 1);

    /* Short delay to ensure device is ready after PWR_UP */
    usleep(2000); /* 2 ms */

    nrf24_set_ce_high(dev);
}

void nrf24_power_up_rx(nrf24_t *dev)
{
    if (!dev) return;

    dev->power_tx = 0;
    uint8_t config;
    nrf24_read_reg(dev, NRF24_CONFIG, &config, 1);

    config |= (NRF24_PWR_UP | NRF24_PRIM_RX);

    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_CONFIG, &config, 1);

    /* Clear IRQ flags */
    uint8_t status = NRF24_RX_DR | NRF24_TX_DS | NRF24_MAX_RT;
    nrf24_write_reg(dev, NRF24_STATUS, &status, 1);

    /* Startup delay after power up */
    usleep(2000); /* 2 ms */

    nrf24_set_ce_high(dev);
}

void nrf24_power_down(nrf24_t *dev)
{
    if (!dev) return;

    uint8_t config;
    nrf24_read_reg(dev, NRF24_CONFIG, &config, 1);
    config &= ~NRF24_PWR_UP;

    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_CONFIG, &config, 1);
}

/* FIFO helpers */

void nrf24_flush_rx(nrf24_t *dev)
{
    if (!dev) return;
    uint8_t cmd = NRF24_FLUSH_RX;
    nrf24_command(dev, &cmd, 1);
}

void nrf24_flush_tx(nrf24_t *dev)
{
    if (!dev) return;
    uint8_t cmd = NRF24_FLUSH_TX;
    nrf24_command(dev, &cmd, 1);
}

/* STATUS register read */
uint8_t nrf24_get_status(nrf24_t *dev)
{
    if (!dev) return 0;
    uint8_t cmd = NRF24_NOP;
    nrf24_command(dev, &cmd, 1);
    return cmd;
}

/* TX part */

/* Send one payload (len <= dev->payload_size).
 * If len < payload_size, the rest is padded with dev->padding byte.
 */
int nrf24_send(nrf24_t *dev, const uint8_t *data, size_t len)
{
    if (!dev || !data) return -1;
    if (len > dev->payload_size) return -2;

    /* If TX FIFO is full or MAX_RT set, flush TX first */
    uint8_t status = nrf24_get_status(dev);
    if (status & (NRF24_TX_FULL | NRF24_MAX_RT)) {
        nrf24_flush_tx(dev);
        /* Clear MAX_RT flag */
        uint8_t clr = NRF24_MAX_RT;
        nrf24_write_reg(dev, NRF24_STATUS, &clr, 1);
    }

    uint8_t buf[1 + 32];
    buf[0] = NRF24_W_TX_PAYLOAD;

    /* Copy data and pad if needed */
    size_t i;
    for (i = 0; i < len; ++i) {
        buf[1 + i] = data[i];
    }
    for (; i < dev->payload_size; ++i) {
        buf[1 + i] = dev->padding;
    }

    nrf24_power_up_tx(dev);
    nrf24_command(dev, buf, 1 + dev->payload_size);

    return 0;
}

/* Check if TX is still in progress.
 * Returns 1 if still sending, 0 if finished or not in TX mode.
 */
int nrf24_is_sending(nrf24_t *dev)
{
    if (!dev) return 0;

    if (dev->power_tx) {
        uint8_t status = nrf24_get_status(dev);
        if (status & (NRF24_TX_DS | NRF24_MAX_RT)) {
            /* Transmission finished or failed: go back to RX mode */
            nrf24_power_up_rx(dev);
            return 0;
        }
        return 1;
    }
    return 0;
}

/* Simple wait until send completes (no timeout).
 * Returns 0 on success.
 */
int nrf24_wait_until_sent(nrf24_t *dev)
{
    if (!dev) return -1;
    while (nrf24_is_sending(dev)) {
        usleep(200); /* 200 us between polls */
    }
    return 0;
}

/* RX part */

int nrf24_data_ready(nrf24_t *dev)
{
    if (!dev) return 0;

    uint8_t status = nrf24_get_status(dev);
    if (status & NRF24_RX_DR) {
        return 1;
    }

    uint8_t fifo;
    nrf24_read_reg(dev, NRF24_FIFO_STATUS, &fifo, 1);
    if (fifo & NRF24_FRX_EMPTY) {
        return 0;
    }
    return 1;
}

/* Read one payload into 'data' buffer.
 * len MUST be >= dev->payload_size.
 */
int nrf24_get_payload(nrf24_t *dev, uint8_t *data, size_t len)
{
    if (!dev || !data) return -1;
    if (len < dev->payload_size) return -2;

    uint8_t buf[1 + 32];
    buf[0] = NRF24_R_RX_PAYLOAD;
    memset(buf + 1, 0, dev->payload_size);

    nrf24_command(dev, buf, 1 + dev->payload_size);

    memcpy(data, buf + 1, dev->payload_size);

    /* Clear RX_DR flag */
    uint8_t status = NRF24_RX_DR;
    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_STATUS, &status, 1);
    nrf24_set_ce_high(dev);

    return (int)dev->payload_size;
}


/* ---- Debug helpers ---- */

void nrf24_debug_dump(nrf24_t *dev)
{
    /* This function prints some key registers for debugging. */
    uint8_t v;
    uint8_t addr[5];

    if (!dev) {
        return;
    }

    printf("---- nRF24 debug dump ----\n");

    /* CONFIG */
    nrf24_read_reg(dev, NRF24_CONFIG, &v, 1);
    printf("CONFIG      = 0x%02X\n", v);

    /* EN_AA, EN_RXADDR */
    nrf24_read_reg(dev, NRF24_EN_AA, &v, 1);
    printf("EN_AA       = 0x%02X\n", v);

    nrf24_read_reg(dev, NRF24_EN_RXADDR, &v, 1);
    printf("EN_RXADDR   = 0x%02X\n", v);

    /* RF_CH, RF_SETUP */
    nrf24_read_reg(dev, NRF24_RF_CH, &v, 1);
    printf("RF_CH       = 0x%02X\n", v);

    nrf24_read_reg(dev, NRF24_RF_SETUP, &v, 1);
    printf("RF_SETUP    = 0x%02X\n", v);

    /* SETUP_RETR */
    nrf24_read_reg(dev, NRF24_SETUP_RETR, &v, 1);
    printf("SETUP_RETR  = 0x%02X\n", v);

    /* STATUS */
    v = nrf24_get_status(dev);
    printf("STATUS      = 0x%02X\n", v);

    /* FIFO_STATUS */
    nrf24_read_reg(dev, NRF24_FIFO_STATUS, &v, 1);
    printf("FIFO_STATUS = 0x%02X\n", v);

    /* TX_ADDR (5 bytes) */
    nrf24_read_reg(dev, NRF24_TX_ADDR, addr, 5);
    printf("TX_ADDR     = %02X %02X %02X %02X %02X\n",
           addr[0], addr[1], addr[2], addr[3], addr[4]);

    /* RX_ADDR_P0 (5 bytes) */
    nrf24_read_reg(dev, NRF24_RX_ADDR_P0, addr, 5);
    printf("RX_ADDR_P0  = %02X %02X %02X %02X %02X\n",
           addr[0], addr[1], addr[2], addr[3], addr[4]);

    /* RX_ADDR_P1 (5 bytes) */
    nrf24_read_reg(dev, NRF24_RX_ADDR_P1, addr, 5);
    printf("RX_ADDR_P1  = %02X %02X %02X %02X %02X\n",
           addr[0], addr[1], addr[2], addr[3], addr[4]);

    printf("--------------------------\n");
}
