#include "mid_timer.h"
#include "servo.h"

volatile uint32_t g_ms_tick = 0;
volatile uint8_t g_control_tick = 0;

void enable_task_interrupt(void)
{
}

void disable_task_interrupt(void)
{
}

void timer_init(void)
{
    NVIC_ClearPendingIRQ(TIMER_TICK_INST_INT_IRQN);
    NVIC_EnableIRQ(TIMER_TICK_INST_INT_IRQN);
}

void TIMER_TICK_INST_IRQHandler(void)
{
    if (DL_TimerA_getPendingInterrupt(TIMER_TICK_INST) == DL_TIMER_IIDX_ZERO)
    {
        g_ms_tick += 20;
        servo_update(g_ms_tick);
        g_control_tick = 1;
    }
}
