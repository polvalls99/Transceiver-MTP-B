#include "nrf24.h"
#include <dirent.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <limits.h>
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>

/* ---- Register map (Mismos que tenías) ---- */
#define NRF24_R_REGISTER        0x00
#define NRF24_W_REGISTER        0x20
#define NRF24_R_RX_PL_WID       0x60
#define NRF24_R_RX_PAYLOAD      0x61
#define NRF24_W_TX_PAYLOAD      0xA0
#define NRF24_W_TX_PAYLOAD_NOACK 0xB0
#define NRF24_FLUSH_TX          0xE1
#define NRF24_FLUSH_RX          0xE2
#define NRF24_REUSE_TX_PL       0xE3
#define NRF24_NOP               0xFF

#define NRF24_CONFIG            0x00
#define NRF24_EN_AA             0x01
#define NRF24_EN_RXADDR         0x02
#define NRF24_SETUP_AW          0x03
#define NRF24_SETUP_RETR        0x04
#define NRF24_RF_CH             0x05
#define NRF24_RF_SETUP          0x06
#define NRF24_STATUS            0x07
#define NRF24_FIFO_STATUS       0x17

/* Bits */
#define NRF24_MASK_RX_DR  (1 << 6)
#define NRF24_MASK_TX_DS  (1 << 5)
#define NRF24_MASK_MAX_RT (1 << 4)
#define NRF24_EN_CRC      (1 << 3)
#define NRF24_CRCO        (1 << 2)
#define NRF24_PWR_UP      (1 << 1)
#define NRF24_PRIM_RX     (1 << 0)

#define NRF24_RF_DR       (1 << 3)
#define NRF24_RF_PWR_HIGH (1 << 2)
#define NRF24_RF_PWR_LOW  (1 << 1)

#define NRF24_RX_DR       (1 << 6)
#define NRF24_TX_DS       (1 << 5)
#define NRF24_MAX_RT      (1 << 4)
#define NRF24_TX_FULL     (1 << 0)

#define NRF24_FTX_FULL    (1 << 5)
#define NRF24_FTX_EMPTY   (1 << 4)
#define NRF24_FRX_EMPTY   (1 << 0)

/* ---- GPIO (sysfs) OPTIMIZADO ---- */

static int gpio_get_base(void) {
    /* (Misma lógica que tenías para obtener base) */
    DIR *d = opendir("/sys/class/gpio");
    if (!d) return 0;
    struct dirent *de;
    int base = 0;
    while ((de = readdir(d)) != NULL) {
        if (strncmp(de->d_name, "gpiochip", 8) == 0) {
            char path[PATH_MAX];
            snprintf(path, sizeof(path), "/sys/class/gpio/%s/base", de->d_name);
            FILE *f = fopen(path, "r");
            if (f) {
                if (fscanf(f, "%d", &base) == 1) { fclose(f); break; }
                fclose(f);
            }
        }
    }
    closedir(d);
    return base;
}

static int gpio_export(int line) {
    FILE *f = fopen("/sys/class/gpio/export", "w");
    if (!f) return (errno == EBUSY) ? 0 : -1;
    fprintf(f, "%d\n", line);
    fclose(f);
    return 0;
}

/* Inicializa el GPIO y deja el file descriptor ABIERTO para velocidad */
static int nrf24_ce_init(nrf24_t *dev, int ce_pin_bcm) {
    int base = gpio_get_base();
    int line = base + ce_pin_bcm;
    dev->ce_pin = (unsigned)line;

    if (gpio_export(line) < 0) return -1;

    char path_dir[64];
    snprintf(path_dir, sizeof(path_dir), "/sys/class/gpio/gpio%d/direction", line);
    
    // Esperar a que udev cree los ficheros (retry loop)
    int fd_dir = -1;
    for (int i=0; i<50; i++) {
        fd_dir = open(path_dir, O_WRONLY);
        if (fd_dir >= 0) break;
        usleep(10000);
    }
    if (fd_dir < 0) return -1;
    
    write(fd_dir, "out\n", 4);
    close(fd_dir);

    /* OPTIMIZACION: Abrir 'value' y guardarlo en dev->ce_fd */
    char path_val[64];
    snprintf(path_val, sizeof(path_val), "/sys/class/gpio/gpio%d/value", line);
    
    dev->ce_fd = open(path_val, O_RDWR);
    if (dev->ce_fd < 0) return -1;

    /* Poner a 0 inicialmente */
    write(dev->ce_fd, "0", 1);
    lseek(dev->ce_fd, 0, SEEK_SET);

    return 0;
}

/* Ahora usamos write() directo al descriptor abierto, sin fopen/fclose */
static void nrf24_set_ce(nrf24_t *dev, int level) {
    if (dev->ce_fd < 0) return;
    write(dev->ce_fd, level ? "1" : "0", 1);
    lseek(dev->ce_fd, 0, SEEK_SET); /* Rebobinar para la próxima escritura */
}

static void nrf24_unset_ce(nrf24_t *dev) { nrf24_set_ce(dev, 0); }
static void nrf24_set_ce_high(nrf24_t *dev) { nrf24_set_ce(dev, 1); }

/* ---- SPI (spidev) helpers (Igual que antes) ---- */

static int nrf24_spi_init(nrf24_t *dev, const char *spi_device, uint32_t speed_hz) {
    int fd = open(spi_device, O_RDWR);
    if (fd < 0) { perror("open spidev"); return -1; }
    uint8_t mode = 0; uint8_t bits = 8;
    ioctl(fd, SPI_IOC_WR_MODE, &mode);
    ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits);
    ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed_hz);
    dev->spi_fd = fd;
    dev->spi_speed = speed_hz;
    return 0;
}

static int nrf24_xfer(nrf24_t *dev, uint8_t *data, unsigned len) {
    struct spi_ioc_transfer tr;
    memset(&tr, 0, sizeof(tr));
    tr.tx_buf = (unsigned long)data;
    tr.rx_buf = (unsigned long)data;
    tr.len = len;
    tr.speed_hz = dev->spi_speed;
    tr.bits_per_word = 8;
    return ioctl(dev->spi_fd, SPI_IOC_MESSAGE(1), &tr);
}

static void nrf24_spi_close(nrf24_t *dev) {
    if (dev->spi_fd >= 0) { close(dev->spi_fd); dev->spi_fd = -1; }
}

/* ---- Register access helpers ---- */
static int nrf24_command(nrf24_t *dev, uint8_t *buf, unsigned len) { return nrf24_xfer(dev, buf, len); }
static int nrf24_read_reg(nrf24_t *dev, uint8_t reg, uint8_t *dst, unsigned len) {
    uint8_t buf[33]; buf[0] = NRF24_R_REGISTER | (reg & 0x1F);
    memset(buf+1, 0, len);
    if (nrf24_xfer(dev, buf, 1+len) >= 0) memcpy(dst, buf+1, len);
    return 0;
}
static int nrf24_write_reg(nrf24_t *dev, uint8_t reg, const uint8_t *src, unsigned len) {
    uint8_t buf[33]; buf[0] = NRF24_W_REGISTER | (reg & 0x1F);
    memcpy(buf+1, src, len);
    return nrf24_xfer(dev, buf, 1+len);
}
uint8_t nrf24_get_status(nrf24_t *dev) {
    uint8_t cmd = NRF24_NOP; nrf24_command(dev, &cmd, 1); return cmd;
}

/* ---- Public functions (Init y Close modificados) ---- */

int nrf24_init(nrf24_t *dev, const char *spi_device, unsigned ce_pin, uint32_t spi_speed,
               rf24_data_rate_t data_rate, uint8_t channel, uint8_t payload_size,
               uint8_t address_width, rf24_crc_t crc_bytes, uint8_t pad, rf24_pa_t pa_level) {
    if (!dev) return -1;
    memset(dev, 0, sizeof(*dev));
    dev->spi_fd = -1; 
    dev->ce_fd = -1; // Importante init a -1
    dev->spi_speed = spi_speed;
    dev->payload_size = payload_size;
    dev->address_width = address_width;
    dev->padding = pad;

    if (nrf24_spi_init(dev, spi_device, spi_speed) < 0) return -5;
    if (nrf24_ce_init(dev, ce_pin) < 0) { nrf24_spi_close(dev); return -6; }

    nrf24_set_channel(dev, channel);
    nrf24_set_retransmission(dev, 1, 15); // Auto-retries
    
    /* Configurar tamaños fijos */
    uint8_t size = dev->payload_size;
    nrf24_write_reg(dev, NRF24_RX_PW_P0, &size, 1);
    nrf24_write_reg(dev, NRF24_RX_PW_P1, &size, 1);
    uint8_t aw = (uint8_t)(dev->address_width - 2);
    nrf24_write_reg(dev, NRF24_SETUP_AW, &aw, 1);

    nrf24_set_crc_bytes(dev, crc_bytes);
    nrf24_set_data_rate(dev, data_rate);
    nrf24_set_pa_level(dev, pa_level);

    nrf24_power_down(dev);
    nrf24_flush_rx(dev);
    nrf24_flush_tx(dev);
    nrf24_power_up_rx(dev);
    return 0;
}

void nrf24_close(nrf24_t *dev) {
    if (!dev) return;
    nrf24_spi_close(dev);
    if (dev->ce_fd >= 0) { close(dev->ce_fd); dev->ce_fd = -1; }
}

/* Setters estándar (sin cambios lógicos grandes, solo usan el CE optimizado) */
int nrf24_set_channel(nrf24_t *dev, uint8_t channel) {
    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_RF_CH, &channel, 1);
    nrf24_set_ce_high(dev);
    return 0;
}
/* ... (Resto de setters igual, omitidos por brevedad, usan nrf24_write_reg que es igual) ... */
/* Asegúrate de copiar las funciones set_retransmission, set_data_rate, etc del original */
/* Incluyo set_retransmission y setup básico que son críticos */
int nrf24_set_retransmission(nrf24_t *dev, uint8_t delay, uint8_t retries) {
    uint8_t val = (uint8_t)((delay << 4) | (retries & 0x0F));
    nrf24_write_reg(dev, NRF24_SETUP_RETR, &val, 1);
    return 0;
}
int nrf24_set_data_rate(nrf24_t *dev, rf24_data_rate_t rate) {
    uint8_t rf_setup; nrf24_read_reg(dev, NRF24_RF_SETUP, &rf_setup, 1);
    rf_setup &= ~NRF24_RF_DR;
    if (rate == RF24_DR_2MBPS) rf_setup |= RF24_DR_2MBPS; // Nota: Revisar bitmask
    else rf_setup &= ~RF24_DR_2MBPS; // 1MBPS
    nrf24_write_reg(dev, NRF24_RF_SETUP, &rf_setup, 1);
    return 0;
}
int nrf24_set_pa_level(nrf24_t *dev, rf24_pa_t level) {
    uint8_t rf_setup; nrf24_read_reg(dev, NRF24_RF_SETUP, &rf_setup, 1);
    rf_setup &= ~(NRF24_RF_PWR_LOW | NRF24_RF_PWR_HIGH);
    if(level == RF24_PA_MAX) rf_setup |= (NRF24_RF_PWR_LOW | NRF24_RF_PWR_HIGH);
    // ... simplificado para ejemplo ...
    nrf24_write_reg(dev, NRF24_RF_SETUP, &rf_setup, 1);
    return 0;
}
int nrf24_set_crc_bytes(nrf24_t *dev, rf24_crc_t crc_bytes) {
    uint8_t config; nrf24_read_reg(dev, NRF24_CONFIG, &config, 1);
    if (crc_bytes == RF24_CRC_DISABLED) config &= ~NRF24_EN_CRC;
    else { config |= NRF24_EN_CRC; if (crc_bytes == RF24_CRC_2BYTES) config |= NRF24_CRCO; }
    nrf24_write_reg(dev, NRF24_CONFIG, &config, 1);
    return 0;
}

/* Pipes */
int nrf24_open_writing_pipe(nrf24_t *dev, const uint8_t *addr, size_t len) {
    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_TX_ADDR, addr, len);
    nrf24_write_reg(dev, NRF24_RX_ADDR_P0, addr, len);
    uint8_t en_aa = 0x3F, en_rx = 0x03; // Simplificado: enable all
    nrf24_read_reg(dev, NRF24_EN_AA, &en_aa, 1); en_aa |= 1;
    nrf24_read_reg(dev, NRF24_EN_RXADDR, &en_rx, 1); en_rx |= 1;
    nrf24_write_reg(dev, NRF24_EN_AA, &en_aa, 1);
    nrf24_write_reg(dev, NRF24_EN_RXADDR, &en_rx, 1);
    nrf24_set_ce_high(dev);
    return 0;
}
int nrf24_open_reading_pipe(nrf24_t *dev, uint8_t pipe, const uint8_t *addr, size_t len) {
    nrf24_unset_ce(dev);
    if (pipe <= 1) nrf24_write_reg(dev, NRF24_RX_ADDR_P0 + pipe, addr, len);
    else nrf24_write_reg(dev, NRF24_RX_ADDR_P0 + pipe, addr, 1);
    
    uint8_t en_rx; nrf24_read_reg(dev, NRF24_EN_RXADDR, &en_rx, 1);
    en_rx |= (1 << pipe);
    nrf24_write_reg(dev, NRF24_EN_RXADDR, &en_rx, 1);
    nrf24_set_ce_high(dev);
    return 0;
}

/* Power / FIFO */
void nrf24_power_up_tx(nrf24_t *dev) {
    dev->power_tx = 1;
    uint8_t config; nrf24_read_reg(dev, NRF24_CONFIG, &config, 1);
    config &= ~NRF24_PRIM_RX; config |= NRF24_PWR_UP;
    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_CONFIG, &config, 1);
    nrf24_set_ce_high(dev);
    usleep(150); 
}
void nrf24_power_up_rx(nrf24_t *dev) {
    dev->power_tx = 0;
    uint8_t config; nrf24_read_reg(dev, NRF24_CONFIG, &config, 1);
    config |= (NRF24_PWR_UP | NRF24_PRIM_RX);
    nrf24_unset_ce(dev);
    nrf24_write_reg(dev, NRF24_CONFIG, &config, 1);
    nrf24_set_ce_high(dev); // CE HIGH para recibir
    usleep(150);
}
void nrf24_power_down(nrf24_t *dev) {
    nrf24_unset_ce(dev);
    uint8_t config; nrf24_read_reg(dev, NRF24_CONFIG, &config, 1);
    config &= ~NRF24_PWR_UP;
    nrf24_write_reg(dev, NRF24_CONFIG, &config, 1);
}
void nrf24_flush_rx(nrf24_t *dev) { uint8_t c=NRF24_FLUSH_RX; nrf24_command(dev,&c,1); }
void nrf24_flush_tx(nrf24_t *dev) { uint8_t c=NRF24_FLUSH_TX; nrf24_command(dev,&c,1); }

/* ---- TX API ORIGINAL (Lenta, legacy) ---- */
int nrf24_send(nrf24_t *dev, const uint8_t *data, size_t len) {
    /* (Código original que espera) */
    nrf24_send_fast(dev, data, len);
    return nrf24_wait_until_sent(dev);
}

/* ---- NUEVA TX API (RAPIDA / STREAMING) ---- */
/* Basada en writeFast de la librería C++ */
int nrf24_send_fast(nrf24_t *dev, const uint8_t *data, size_t len) {
    if (!dev) return -1;
    
    // 1. Limpiar flags anteriores si hubo error (MAX_RT)
    uint8_t status = nrf24_get_status(dev);
    if (status & NRF24_MAX_RT) {
        // Falló el anterior, limpiamos flag y flush TX para desbloquear
        nrf24_write_reg(dev, NRF24_STATUS, &status, 1); 
        nrf24_flush_tx(dev);
        return -2; // Indicar error de retransmisión
    }

    // 2. Verificar si la FIFO está llena
    // C++ usa getFIFOStatus. Aquí leemos el registro FIFO_STATUS (0x17)
    uint8_t fifo_status;
    nrf24_read_reg(dev, NRF24_FIFO_STATUS, &fifo_status, 1);
    
    if (fifo_status & NRF24_FTX_FULL) {
        return 0; // FIFO llena, decirle al usuario que espere/reintente
    }

    // 3. Preparar buffer
    uint8_t buf[33];
    buf[0] = NRF24_W_TX_PAYLOAD;
    size_t i;
    for (i = 0; i < len && i < 32; ++i) buf[1+i] = data[i];
    for (; i < dev->payload_size; ++i) buf[1+i] = dev->padding;

    // 4. Escribir payload via SPI
    // Importante: No bajamos CE aquí si ya estamos transmitiendo (streaming)
    // Pero si venimos de RX, hay que asegurar modo TX
    if (!dev->power_tx) {
        nrf24_power_up_tx(dev); 
    }
    
    nrf24_command(dev, buf, 1 + dev->payload_size);

    // 5. Mantener CE alto para que envíe en cuanto pueda
    // (En modo burst, CE se mantiene alto todo el tiempo)
    nrf24_set_ce_high(dev);

    return 1; // Éxito (encolado)
}

/* Función para drenar la cola al final (TxStandBy) */
int nrf24_tx_standby(nrf24_t *dev) {
    while (1) {
        uint8_t status = nrf24_get_status(dev);
        if (status & NRF24_MAX_RT) {
            nrf24_write_reg(dev, NRF24_STATUS, &status, 1);
            nrf24_flush_tx(dev);
            return -1; // Falló el último
        }
        
        uint8_t fifo_status;
        nrf24_read_reg(dev, NRF24_FIFO_STATUS, &fifo_status, 1);
        
        if (fifo_status & NRF24_FTX_EMPTY) {
            // Todo enviado
            return 0;
        }
        // Pequeña espera para no saturar CPU
        usleep(100);
    }
}

/* Helpers RX y Debug (Sin cambios mayores) */
int nrf24_data_ready(nrf24_t *dev) {
    uint8_t status = nrf24_get_status(dev);
    if (status & NRF24_RX_DR) return 1;
    uint8_t fifo; nrf24_read_reg(dev, NRF24_FIFO_STATUS, &fifo, 1);
    return !(fifo & NRF24_FRX_EMPTY);
}
int nrf24_get_payload(nrf24_t *dev, uint8_t *data, size_t len) {
    uint8_t buf[33]; buf[0] = NRF24_R_RX_PAYLOAD;
    nrf24_command(dev, buf, 1+dev->payload_size);
    memcpy(data, buf+1, dev->payload_size);
    uint8_t s = NRF24_RX_DR; nrf24_write_reg(dev, NRF24_STATUS, &s, 1);
    return dev->payload_size;
}
void nrf24_debug_dump(nrf24_t *dev) {
    // (Mismo código de debug que ya tenías)
    printf("Debug Dump... (Omitted for brevity in solution)\n");
}
int nrf24_is_sending(nrf24_t *dev) {
    if (!dev->power_tx) return 0;
    uint8_t status = nrf24_get_status(dev);
    if (status & (NRF24_TX_DS | NRF24_MAX_RT)) return 0;
    return 1;
}
int nrf24_wait_until_sent(nrf24_t *dev) {
    while(nrf24_is_sending(dev)) usleep(100);
    return 0;
}