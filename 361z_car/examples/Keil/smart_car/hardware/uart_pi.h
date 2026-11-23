#ifndef UART_PI_H
#define UART_PI_H

/* Link to the Orange Pi: UART3, PA14 = TX, PA13 = RX, 115200 8N1.
 * Both directions are buffered: send_char() only enqueues a byte and the
 * uart_pi_poll() drains the TX queue from the main loop. */

void uart_pi_init(void);
void uart_pi_send_char(char ch);
void uart_pi_send_string(const char *str);
void uart_pi_poll(void);
int  uart_pi_get_char(char *ch);

#endif
