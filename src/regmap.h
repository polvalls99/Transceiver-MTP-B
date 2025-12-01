/* ---- Register map ---- */
#define NRF24_R_REGISTER        0x00
#define NRF24_W_REGISTER        0x20
#define NRF24_R_RX_PL_WID       0x60
#define NRF24_R_RX_PAYLOAD      0x61
#define NRF24_W_TX_PAYLOAD      0xA0
#define NRF24_W_ACK_PAYLOAD     0xA8
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
#define NRF24_OBSERVE_TX        0x08
#define NRF24_RPD               0x09
#define NRF24_RX_ADDR_P0        0x0A
#define NRF24_RX_ADDR_P1        0x0B
#define NRF24_RX_ADDR_P2        0x0C
#define NRF24_RX_ADDR_P3        0x0D
#define NRF24_RX_ADDR_P4        0x0E
#define NRF24_RX_ADDR_P5        0x0F
#define NRF24_TX_ADDR           0x10
#define NRF24_RX_PW_P0          0x11
#define NRF24_RX_PW_P1          0x12
#define NRF24_RX_PW_P2          0x13
#define NRF24_RX_PW_P3          0x14
#define NRF24_RX_PW_P4          0x15
#define NRF24_RX_PW_P5          0x16
#define NRF24_FIFO_STATUS       0x17
#define NRF24_DYNPD             0x1C
#define NRF24_FEATURE           0x1D

/* CONFIG bits */
#define NRF24_MASK_RX_DR  (1 << 6)
#define NRF24_MASK_TX_DS  (1 << 5)
#define NRF24_MASK_MAX_RT (1 << 4)
#define NRF24_EN_CRC      (1 << 3)
#define NRF24_CRCO        (1 << 2)
#define NRF24_PWR_UP      (1 << 1)
#define NRF24_PRIM_RX     (1 << 0)

/* RF_SETUP bits */
//#define NRF24_RF_DR_LOW   (1 << 5)
#define NRF24_PLL_LOCK    (1 << 4)
#define NRF24_RF_DR       (1 << 3)
#define NRF24_RF_PWR_HIGH (1 << 2)
#define NRF24_RF_PWR_LOW  (1 << 1)

/* STATUS bits */
#define NRF24_RX_DR       (1 << 6)
#define NRF24_TX_DS       (1 << 5)
#define NRF24_MAX_RT      (1 << 4)
#define NRF24_TX_FULL     (1 << 0)

/* FIFO_STATUS bits */
#define NRF24_FTX_REUSE   (1 << 6)
#define NRF24_FTX_FULL    (1 << 5)
#define NRF24_FTX_EMPTY   (1 << 4)
#define NRF24_FRX_FULL    (1 << 1)
#define NRF24_FRX_EMPTY   (1 << 0)


