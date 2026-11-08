#include "motor.h"
#include "ti_msp_dl_config.h"

#define M1_IN1_PIN       DL_GPIO_PIN_4
#define M1_IN2_PIN       DL_GPIO_PIN_5
#define M2_IN1_PIN       DL_GPIO_PIN_12
#define M2_IN2_PIN       DL_GPIO_PIN_13
#define STBY_PIN         DL_GPIO_PIN_15

#define M1_IN1_IOMUX     IOMUX_PINCM17
#define M1_IN2_IOMUX     IOMUX_PINCM18
#define M2_IN1_IOMUX     IOMUX_PINCM29
#define M2_IN2_IOMUX     IOMUX_PINCM30
#define STBY_IOMUX       IOMUX_PINCM32

#define MOTOR_PWM_MAX    10000

static int32_t clamp_pwm(int32_t v)
{
    if (v > MOTOR_PWM_MAX)  return MOTOR_PWM_MAX;
    if (v < -MOTOR_PWM_MAX) return -MOTOR_PWM_MAX;
    return v;
}

void motor_init(void)
{
    DL_GPIO_initDigitalOutput(M1_IN1_IOMUX);
    DL_GPIO_initDigitalOutput(M1_IN2_IOMUX);
    DL_GPIO_initDigitalOutput(M2_IN1_IOMUX);
    DL_GPIO_initDigitalOutput(M2_IN2_IOMUX);
    DL_GPIO_initDigitalOutput(STBY_IOMUX);

    DL_GPIO_clearPins(
        GPIOB,
        M1_IN1_PIN | M1_IN2_PIN | M2_IN1_PIN | M2_IN2_PIN | STBY_PIN);

    DL_GPIO_enableOutput(
        GPIOB,
        M1_IN1_PIN | M1_IN2_PIN | M2_IN1_PIN | M2_IN2_PIN | STBY_PIN);

    /* 0% duty before enabling the bridge. */
    DL_TimerG_setCaptureCompareValue(
        PWM_MOTOR_INST, 0, GPIO_PWM_MOTOR_C0_IDX);
    DL_TimerG_setCaptureCompareValue(
        PWM_MOTOR_INST, 0, GPIO_PWM_MOTOR_C1_IDX);

    /* Keep the bridge disabled until the control loop is ready. */
    DL_GPIO_clearPins(GPIOB, STBY_PIN);
}

void motor_enable(int enable)
{
    if (enable)
        DL_GPIO_setPins(GPIOB, STBY_PIN);
    else
        DL_GPIO_clearPins(GPIOB, STBY_PIN);
}

static void motor_left(int32_t duty)
{
    duty = clamp_pwm(duty);

    if (duty > 0)
    {
        DL_GPIO_setPins(GPIOB, M1_IN1_PIN);
        DL_GPIO_clearPins(GPIOB, M1_IN2_PIN);
        DL_TimerG_setCaptureCompareValue(
            PWM_MOTOR_INST, (uint32_t)duty, GPIO_PWM_MOTOR_C0_IDX);
    }
    else if (duty < 0)
    {
        DL_GPIO_clearPins(GPIOB, M1_IN1_PIN);
        DL_GPIO_setPins(GPIOB, M1_IN2_PIN);
        DL_TimerG_setCaptureCompareValue(
            PWM_MOTOR_INST, (uint32_t)(-duty), GPIO_PWM_MOTOR_C0_IDX);
    }
    else
    {
        DL_GPIO_clearPins(GPIOB, M1_IN1_PIN | M1_IN2_PIN);
        DL_TimerG_setCaptureCompareValue(
            PWM_MOTOR_INST, 0, GPIO_PWM_MOTOR_C0_IDX);
    }
}

static void motor_right(int32_t duty)
{
    /* M2 is mounted mirrored: a positive duty must drive the wheel forward,
     * which needs the opposite bridge polarity than M1. */
    duty = clamp_pwm(-duty);

    if (duty > 0)
    {
        DL_GPIO_setPins(GPIOB, M2_IN1_PIN);
        DL_GPIO_clearPins(GPIOB, M2_IN2_PIN);
        DL_TimerG_setCaptureCompareValue(
            PWM_MOTOR_INST, (uint32_t)duty, GPIO_PWM_MOTOR_C1_IDX);
    }
    else if (duty < 0)
    {
        DL_GPIO_clearPins(GPIOB, M2_IN1_PIN);
        DL_GPIO_setPins(GPIOB, M2_IN2_PIN);
        DL_TimerG_setCaptureCompareValue(
            PWM_MOTOR_INST, (uint32_t)(-duty), GPIO_PWM_MOTOR_C1_IDX);
    }
    else
    {
        DL_GPIO_clearPins(GPIOB, M2_IN1_PIN | M2_IN2_PIN);
        DL_TimerG_setCaptureCompareValue(
            PWM_MOTOR_INST, 0, GPIO_PWM_MOTOR_C1_IDX);
    }
}

void motor_set(int32_t left, int32_t right)
{
    motor_left(left);
    motor_right(right);
}

void motor_stop(void)
{
    motor_set(0, 0);
}
