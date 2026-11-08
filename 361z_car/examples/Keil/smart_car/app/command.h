#ifndef COMMAND_H
#define COMMAND_H

#include <stdint.h>

void command_init(void);
void command_poll(void);
uint32_t command_last_tick(void);
int command_active(void);
void command_clear_active(void);

#endif
