#include "pid.h"

void pid_init(PID *pid, float kp, float ki, float kd, float out_max, float integ_max)
{
    pid->kp = kp;
    pid->ki = ki;
    pid->kd = kd;
    pid->integ = 0.0f;
    pid->prev_error = 0.0f;
    pid->out_max = out_max;
    pid->integ_max = integ_max;
}

void pid_reset(PID *pid)
{
    pid->integ = 0.0f;
    pid->prev_error = 0.0f;
}

float pid_calc(PID *pid, float target, float actual, float dt)
{
    float error = target - actual;
    float deriv;
    float out;

    pid->integ += error * dt;
    if (pid->integ > pid->integ_max)  pid->integ = pid->integ_max;
    if (pid->integ < -pid->integ_max) pid->integ = -pid->integ_max;

    deriv = (error - pid->prev_error) / dt;
    pid->prev_error = error;

    out = pid->kp * error + pid->ki * pid->integ + pid->kd * deriv;

    if (out > pid->out_max)  out = pid->out_max;
    if (out < -pid->out_max) out = -pid->out_max;

    return out;
}
