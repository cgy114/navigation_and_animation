#include "mid_debug_uart.h"
#include "uart_pi.h"

#define DEBUG_RX_SIZE 128
/* Fits the complete startup help plus READY before the main loop starts. */
#define DEBUG_TX_SIZE 2048

static volatile uint8_t rx_buf[DEBUG_RX_SIZE];
static volatile uint16_t rx_head = 0;
static volatile uint16_t rx_tail = 0;

/* Transmit queue: send_* only enqueues, debug_uart_poll() feeds the UART one
 * byte at a time while it is free. The main loop never waits for the shifter,
 * so a 9600 baud line cannot stall the 20 ms control tick. */
static volatile uint8_t tx_buf[DEBUG_TX_SIZE];
static volatile uint16_t tx_head = 0;
static volatile uint16_t tx_tail = 0;

void debug_uart_init(void)
{
    /* RX only; transmission is polled. */
    DL_UART_Main_disableInterrupt(UART_DEBUG_INST, DL_UART_MAIN_INTERRUPT_TX);
    DL_UART_Main_setRXFIFOThreshold(UART_DEBUG_INST, DL_UART_RX_FIFO_LEVEL_ONE_ENTRY);
    NVIC_ClearPendingIRQ(UART_DEBUG_INST_INT_IRQN);
    NVIC_EnableIRQ(UART_DEBUG_INST_INT_IRQN);
}

void debug_uart_set_baud_9600(void)
{
    DL_UART_Main_setBaudRateDivisor(UART_DEBUG_INST,
        UART_DEBUG_IBRD_40_MHZ_9600_BAUD,
        UART_DEBUG_FBRD_40_MHZ_9600_BAUD);
}

void debug_uart_send_char(char ch)
{
    uint16_t next = (uint16_t)((tx_head + 1U) % DEBUG_TX_SIZE);

    /* Mirror to the Orange Pi link; that queue is drained the same way. */
    uart_pi_send_char(ch);

    if (next == tx_tail) return;      /* queue full: drop a byte, never block */
    tx_buf[tx_head] = (uint8_t)ch;
    tx_head = next;
}

void debug_uart_send_string(const char *str)
{
    while (*str)
    {
        debug_uart_send_char(*str++);
    }
}

/* Call from the main loop: pushes at most one byte per call. */
void debug_uart_poll(void)
{
    if (tx_tail == tx_head) return;
    if (DL_UART_isBusy(UART_DEBUG_INST)) return;
    DL_UART_Main_transmitData(UART_DEBUG_INST, tx_buf[tx_tail]);
    tx_tail = (uint16_t)((tx_tail + 1U) % DEBUG_TX_SIZE);
}

int debug_uart_get_char(char *ch)
{
    if (rx_tail == rx_head) return 0;
    *ch = (char)rx_buf[rx_tail];
    rx_tail = (uint16_t)((rx_tail + 1U) % DEBUG_RX_SIZE);
    return 1;
}

void UART_DEBUG_INST_IRQHandler(void)
{
    if (DL_UART_Main_getPendingInterrupt(UART_DEBUG_INST) == DL_UART_IIDX_RX)
    {
        while (!DL_UART_isRXFIFOEmpty(UART_DEBUG_INST))
        {
            uint8_t b = DL_UART_Main_receiveData(UART_DEBUG_INST);
            uint16_t next = (uint16_t)((rx_head + 1U) % DEBUG_RX_SIZE);
            if (next != rx_tail)
            {
                rx_buf[rx_head] = b;
                rx_head = next;
            }
        }
    }
}
