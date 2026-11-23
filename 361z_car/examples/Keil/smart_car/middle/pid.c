#include "pid.h"

/* Dead-band compensation: a motor needs a minimum duty before it starts to
 * turn. Adding a constant in the direction of the output beats that without
 * fighting a reverse command, which a plain "+400" would do: with Kp = 4000
 * a constant 400 cancels a 0.1 m/s error completely, so slow reverse and
 * slow pivot turns produced no motion at all. */
#define PID_DEADBAND_COMP 400.0f

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

    /* Only help the direction the loop already wants to go. */
    if (out > 0.0f)
        out += PID_DEADBAND_COMP;
    else if (out < 0.0f)
        out -= PID_DEADBAND_COMP;

    if (out > pid->out_max)  out = pid->out_max;
    if (out < -pid->out_max) out = -pid->out_max;

    return out;
}
