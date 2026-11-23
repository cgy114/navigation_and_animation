#ifndef SERVO_H
#define SERVO_H

#include <stdint.h>

#define SERVO_MIN_PULSE_US 1000U
#define SERVO_CENTER_PULSE_US 1500U
#define SERVO_MAX_PULSE_US 2000U
#define SERVO_LEFT_PULSE_US 1300U
#define SERVO_RIGHT_PULSE_US 1700U

void servo_init(void);
void servo_set_angle(unsigned degrees);
void servo_set_pulse_us(unsigned pulse_us);
void servo_start_sweep(uint32_t now_ms);
void servo_update(uint32_t now_ms);

#endif
