#ifndef ENCODER_H
#define ENCODER_H

#include <stdint.h>

void encoder_init(void);
void encoder_update(void);
void encoder_reset_totals(void);

int encoder_left_delta(void);
int encoder_right_delta(void);

int32_t encoder_left_total(void);
int32_t encoder_right_total(void);

#endif
