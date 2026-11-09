#ifndef SERVO_H
#define SERVO_H

#include <stdint.h>

void servo_init(void);
void servo_set_angle(unsigned degrees);
void servo_set_pulse_us(unsigned pulse_us);
void servo_start_sweep(uint32_t now_ms);
void servo_update(uint32_t now_ms);

#endif
