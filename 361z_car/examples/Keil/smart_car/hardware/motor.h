#ifndef MOTOR_H
#define MOTOR_H

#include <stdint.h>

void motor_init(void);
void motor_enable(int enable);
void motor_set(int32_t left, int32_t right);
void motor_stop(void);

#endif
