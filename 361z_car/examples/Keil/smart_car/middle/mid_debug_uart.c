#include "mid_debug_uart.h"

#define DEBUG_RX_SIZE 128

static volatile uint8_t rx_buf[DEBUG_RX_SIZE];
static volatile uint16_t rx_head = 0;
static volatile uint16_t rx_tail = 0;

void debug_uart_init(void)
{
    NVIC_ClearPendingIRQ(UART_DEBUG_INST_INT_IRQN);
    NVIC_EnableIRQ(UART_DEBUG_INST_INT_IRQN);
}

void debug_uart_set_baud_115200(void)
{
    DL_UART_Main_setBaudRateDivisor(UART_DEBUG_INST, 21, 45);
}

void debug_uart_send_char(char ch)
{
    while (DL_UART_isBusy(UART_DEBUG_INST) == true);
    DL_UART_Main_transmitData(UART_DEBUG_INST, (uint8_t)ch);
}

void debug_uart_send_string(const char *str)
{
    while (*str)
    {
        debug_uart_send_char(*str++);
    }
}

int debug_uart_get_char(char *ch)
{
    if (rx_tail == rx_head) return 0;
    *ch = (char)rx_buf[rx_tail];
    rx_tail = (rx_tail + 1) % DEBUG_RX_SIZE;
    return 1;
}

void UART_DEBUG_INST_IRQHandler(void)
{
    if (DL_UART_getPendingInterrupt(UART_DEBUG_INST) == DL_UART_IIDX_RX)
    {
        uint8_t b = DL_UART_Main_receiveData(UART_DEBUG_INST);
        uint16_t next = (rx_head + 1) % DEBUG_RX_SIZE;
        if (next != rx_tail)
        {
            rx_buf[rx_head] = b;
            rx_head = next;
        }
    }
}
