#ifndef PID_H
#define PID_H

typedef struct
{
    float kp;
    float ki;
    float kd;
    float integ;
    float prev_error;
    float out_max;
    float integ_max;
} PID;

void pid_init(PID *pid, float kp, float ki, float kd, float out_max, float integ_max);
void pid_reset(PID *pid);
float pid_calc(PID *pid, float target, float actual, float dt);

#endif
