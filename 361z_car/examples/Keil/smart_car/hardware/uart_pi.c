#include "uart_pi.h"
#include "ti_msp_dl_config.h"

#define PI_RX_SIZE 256
#define PI_TX_SIZE 2048

static volatile uint8_t rx_buf[PI_RX_SIZE];
static volatile uint16_t rx_head = 0;
static volatile uint16_t rx_tail = 0;

/* Transmit queue fed by uart_pi_poll(), same scheme as the debug UART. */
static volatile uint8_t tx_buf[PI_TX_SIZE];
static volatile uint16_t tx_head = 0;
static volatile uint16_t tx_tail = 0;

static volatile uint8_t ready = 0;

void uart_pi_init(void)
{
    DL_UART_Main_reset(UART3);
    DL_UART_Main_enablePower(UART3);
    delay_cycles(POWER_STARTUP_DELAY);

    /* PA14 = UART3_TX (PINCM36), PA13 = UART3_RX (PINCM35). */
    DL_GPIO_initPeripheralOutputFunction(IOMUX_PINCM36, IOMUX_PINCM36_PF_UART3_TX);
    DL_GPIO_initPeripheralInputFunction(IOMUX_PINCM35, IOMUX_PINCM35_PF_UART3_RX);

    static const DL_UART_Main_ClockConfig clock_cfg = {
        .clockSel    = DL_UART_MAIN_CLOCK_BUSCLK,
        .divideRatio = DL_UART_MAIN_CLOCK_DIVIDE_RATIO_1
    };
    static const DL_UART_Main_Config cfg = {
        .mode        = DL_UART_MAIN_MODE_NORMAL,
        .direction   = DL_UART_MAIN_DIRECTION_TX_RX,
        .flowControl = DL_UART_MAIN_FLOW_CONTROL_NONE,
        .parity      = DL_UART_MAIN_PARITY_NONE,
        .wordLength  = DL_UART_MAIN_WORD_LENGTH_8_BITS,
        .stopBits    = DL_UART_MAIN_STOP_BITS_ONE
    };

    DL_UART_Main_setClockConfig(UART3, (DL_UART_Main_ClockConfig *)&clock_cfg);
    DL_UART_Main_init(UART3, (DL_UART_Main_Config *)&cfg);

    /* UART3 is on the 80 MHz MCLK bus, unlike UART0/1 on 40 MHz ULPCLK. */
    DL_UART_Main_setOversampling(UART3, DL_UART_OVERSAMPLING_RATE_16X);
    DL_UART_Main_setBaudRateDivisor(UART3, 43U, 26U);

    DL_UART_Main_disableInterrupt(UART3, DL_UART_MAIN_INTERRUPT_TX);
    DL_UART_Main_setRXFIFOThreshold(UART3, DL_UART_RX_FIFO_LEVEL_ONE_ENTRY);
    DL_UART_Main_enableInterrupt(UART3, DL_UART_MAIN_INTERRUPT_RX);
    DL_UART_Main_enable(UART3);

    NVIC_ClearPendingIRQ(UART3_INT_IRQn);
    NVIC_SetPriority(UART3_INT_IRQn, 3);
    NVIC_EnableIRQ(UART3_INT_IRQn);

    ready = 1;
}

void uart_pi_send_char(char ch)
{
    uint16_t next;

    if (!ready) return;

    next = (uint16_t)((tx_head + 1U) % PI_TX_SIZE);
    if (next == tx_tail) return;      /* queue full: drop a byte, never block */
    tx_buf[tx_head] = (uint8_t)ch;
    tx_head = next;
}

void uart_pi_send_string(const char *str)
{
    if (!ready) return;
    while (*str)
    {
        uart_pi_send_char(*str++);
    }
}

/* Call from the main loop: pushes at most one byte per call. */
void uart_pi_poll(void)
{
    if (!ready) return;
    if (tx_tail == tx_head) return;
    if (DL_UART_isBusy(UART3)) return;
    DL_UART_Main_transmitData(UART3, tx_buf[tx_tail]);
    tx_tail = (uint16_t)((tx_tail + 1U) % PI_TX_SIZE);
}

int uart_pi_get_char(char *ch)
{
    if (rx_tail == rx_head) return 0;
    *ch = (char)rx_buf[rx_tail];
    rx_tail = (uint16_t)((rx_tail + 1U) % PI_RX_SIZE);
    return 1;
}

void UART3_IRQHandler(void)
{
    if (DL_UART_Main_getPendingInterrupt(UART3) == DL_UART_IIDX_RX)
    {
        while (!DL_UART_isRXFIFOEmpty(UART3))
        {
            uint8_t b = DL_UART_Main_receiveData(UART3);
            uint16_t next = (uint16_t)((rx_head + 1U) % PI_RX_SIZE);
            if (next != rx_tail)
            {
                rx_buf[rx_head] = b;
                rx_head = next;
            }
        }
    }
}
