#ifndef __MID_TIMER_H__
#define __MID_TIMER_H__

#include "ti_msp_dl_config.h"
#include <stdint.h>

extern volatile uint32_t g_ms_tick;
extern volatile uint8_t g_control_tick;

void timer_init(void);
void enable_task_interrupt(void);
void disable_task_interrupt(void);

#endif
