#ifndef MID_DEBUG_UART_H
#define MID_DEBUG_UART_H

#include "ti_msp_dl_config.h"

void debug_uart_init(void);
void debug_uart_set_baud_115200(void);

void debug_uart_send_char(char ch);
void debug_uart_send_string(const char *str);

int debug_uart_get_char(char *ch);

#endif
