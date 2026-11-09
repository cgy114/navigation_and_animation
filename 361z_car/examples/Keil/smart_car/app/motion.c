#include "motion.h"
#include "motor.h"
#include "encoder.h"
#include "pid.h"
#include <math.h>

static PID pid_left;
static PID pid_right;

static float target_v = 0.0f;
static float target_w = 0.0f;
static int32_t direct_left = 0;
static int32_t direct_right = 0;
static int direct_mode = 0;

void motion_init(void)
{
    pid_init(&pid_left,  4000.0f, 1500.0f, 0.0f, 10000.0f, 5000.0f);
    pid_init(&pid_right, 4000.0f, 1500.0f, 0.0f, 10000.0f, 5000.0f);
    target_v = 0.0f;
    target_w = 0.0f;
    direct_mode = 0;
    odom_init();
}

void motion_set_target(float v_mps, float w_radps)
{
    if (v_mps > 1.0f)  v_mps = 1.0f;
    if (v_mps < -1.0f) v_mps = -1.0f;
    if (w_radps > 3.0f)  w_radps = 3.0f;
    if (w_radps < -3.0f) w_radps = -3.0f;

    target_v = v_mps;
    target_w = w_radps;
    if (direct_mode)
    {
        pid_reset(&pid_left);
        pid_reset(&pid_right);
        direct_mode = 0;
    }
}

void motion_set_direct_pwm(int32_t left, int32_t right)
{
    target_v = 0.0f;
    target_w = 0.0f;
    pid_reset(&pid_left);
    pid_reset(&pid_right);
    direct_left = left;
    direct_right = right;
    direct_mode = 1;
    motor_set(left, right);
}

void motion_stop(void)
{
    target_v = 0.0f;
    target_w = 0.0f;
    direct_mode = 0;
    pid_reset(&pid_left);
    pid_reset(&pid_right);
    motor_stop();
}

void motion_set_pid(float kp, float ki, float kd)
{
    pid_init(&pid_left,  kp, ki, kd, 10000.0f, 5000.0f);
    pid_init(&pid_right, kp, ki, kd, 10000.0f, 5000.0f);
}

void motion_get_pid(float *kp, float *ki, float *kd)
{
    *kp = pid_left.kp;
    *ki = pid_left.ki;
    *kd = pid_left.kd;
}

void motion_update(int left_delta, int right_delta, float yaw_rad, int imu_ok)
{
    float v_left;
    float v_right;
    float target_left;
    float target_right;
    float pwm_left;
    float pwm_right;

    if (direct_mode)
    {
        odom_update(left_delta, right_delta, yaw_rad, imu_ok);
        motor_set(direct_left, direct_right);
        return;
    }

    if (!imu_ok)
    {
        motion_stop();
        return;
    }

    v_left  = (float)left_delta  * METERS_PER_COUNT / ODOM_DT;
    v_right = (float)right_delta * METERS_PER_COUNT / ODOM_DT;

    target_left  = target_v - target_w * TRACK_WIDTH_M * 0.5f;
    target_right = target_v + target_w * TRACK_WIDTH_M * 0.5f;

    odom_update(left_delta, right_delta, yaw_rad, imu_ok);

    /* Stop cleanly when the car is already still. */
    if (fabsf(target_left) < 0.005f && fabsf(v_left) < 0.01f)
    {
        pid_reset(&pid_left);
        pwm_left = 0.0f;
    }
    else
    {
        pwm_left = pid_calc(&pid_left, target_left, v_left, ODOM_DT);
    }

    if (fabsf(target_right) < 0.005f && fabsf(v_right) < 0.01f)
    {
        pid_reset(&pid_right);
        pwm_right = 0.0f;
    }
    else
    {
        pwm_right = pid_calc(&pid_right, target_right, v_right, ODOM_DT);
    }

    motor_set((int32_t)pwm_left, (int32_t)pwm_right);
}

const OdomState *motion_get_odom(void)
{
    return odom_get();
}
