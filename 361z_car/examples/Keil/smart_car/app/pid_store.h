#ifndef PID_STORE_H
#define PID_STORE_H

#include <stdint.h>

typedef struct {
    int32_t kp;
    int32_t ki;
    int32_t kd;
} PidGains;

void pid_store_defaults(PidGains *gains);
int pid_store_valid_gains(const PidGains *gains);
int pid_store_load(PidGains *gains);
int pid_store_save(const PidGains *gains);

#endif
