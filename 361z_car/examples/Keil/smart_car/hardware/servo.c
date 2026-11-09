#include "servo.h"
#include "ti_msp_dl_config.h"

/* PA15 uses TIMA1_CCP0.
 * 80 MHz BUSCLK / 80 = 1 MHz. The receiver reference period is ~13955 us.
 * Count up: output goes high at zero and low at the compare value, so the
 * compare value in ticks equals the high pulse width in microseconds. */
#define SERVO_TIMER TIMA1
#define SERVO_PERIOD_TICKS 13955U
#define SERVO_REFERENCE_PULSE_TICKS 1524U
#define SERVO_MIN_PULSE_TICKS 1300U
#define SERVO_MAX_PULSE_TICKS 1700U
#define SERVO_TEST_LOW_PULSE_TICKS SERVO_MIN_PULSE_TICKS
#define SERVO_TEST_HIGH_PULSE_TICKS SERVO_MAX_PULSE_TICKS
#define SERVO_TEST_HOLD_MS 1000U
#define SERVO_TEST_PERIOD_MS (2U * SERVO_TEST_HOLD_MS)
static volatile uint8_t sweep_enabled = 0U;
static uint32_t sweep_start_ms = 0U;
static uint32_t last_sweep_ms = UINT32_MAX;

static void write_pulse_us(uint32_t pulse_us)
{
    DL_TimerA_setCaptureCompareValue(SERVO_TIMER, pulse_us, DL_TIMER_CC_0_INDEX);
}

void servo_init(void)
{
    DL_TimerA_ClockConfig clock_config = {
        .clockSel = DL_TIMER_CLOCK_BUSCLK,
        .divideRatio = DL_TIMER_CLOCK_DIVIDE_1,
        .prescale = 79U
    };
    const DL_TimerA_PWMConfig pwm_config = {
        .pwmMode = DL_TIMER_PWM_MODE_EDGE_ALIGN_UP,
        .period = SERVO_PERIOD_TICKS,
        .isTimerWithFourCC = false,
        .startTimer = DL_TIMER_STOP
    };

    DL_TimerA_reset(SERVO_TIMER);
    DL_TimerA_enablePower(SERVO_TIMER);
    delay_cycles(POWER_STARTUP_DELAY);

    DL_GPIO_initPeripheralOutputFunction(IOMUX_PINCM37, IOMUX_PINCM37_PF_TIMA1_CCP0);
    DL_GPIO_enableOutput(GPIOA, DL_GPIO_PIN_15);

    DL_TimerA_setClockConfig(SERVO_TIMER, &clock_config);
    DL_TimerA_initPWMMode(SERVO_TIMER, &pwm_config);
    DL_TimerA_setCounterControl(SERVO_TIMER,
        DL_TIMER_CZC_CCCTL0_ZCOND, DL_TIMER_CAC_CCCTL0_ACOND,
        DL_TIMER_CLC_CCCTL0_LCOND);
    DL_TimerA_setCaptureCompareOutCtl(SERVO_TIMER,
        DL_TIMER_CC_OCTL_INIT_VAL_LOW, DL_TIMER_CC_OCTL_INV_OUT_DISABLED,
        DL_TIMER_CC_OCTL_SRC_FUNCVAL, DL_TIMERA_CAPTURE_COMPARE_0_INDEX);
    DL_TimerA_setCaptCompUpdateMethod(SERVO_TIMER,
        DL_TIMER_CC_UPDATE_METHOD_IMMEDIATE, DL_TIMERA_CAPTURE_COMPARE_0_INDEX);
    DL_TimerA_setCaptureCompareValue(SERVO_TIMER,
        SERVO_REFERENCE_PULSE_TICKS, DL_TIMER_CC_0_INDEX);
    DL_TimerA_enableClock(SERVO_TIMER);
    DL_TimerA_setCCPDirection(SERVO_TIMER, DL_TIMER_CC0_OUTPUT);
    DL_TimerA_startCounter(SERVO_TIMER);

    sweep_enabled = 0U;
    sweep_start_ms = 0U;
    last_sweep_ms = UINT32_MAX;
}

void servo_set_angle(unsigned degrees)
{
    uint32_t pulse;
    if (degrees > 180U) degrees = 180U;
    pulse = SERVO_MIN_PULSE_TICKS +
        ((SERVO_MAX_PULSE_TICKS - SERVO_MIN_PULSE_TICKS) * degrees) / 180U;
    servo_set_pulse_us(pulse);
}

void servo_set_pulse_us(unsigned pulse_us)
{
    if (pulse_us < SERVO_MIN_PULSE_TICKS) pulse_us = SERVO_MIN_PULSE_TICKS;
    if (pulse_us > SERVO_MAX_PULSE_TICKS) pulse_us = SERVO_MAX_PULSE_TICKS;
    sweep_enabled = 0U;
    write_pulse_us(pulse_us);
}

void servo_start_sweep(uint32_t now_ms)
{
    sweep_enabled = 0U;
    sweep_start_ms = now_ms;
    last_sweep_ms = UINT32_MAX;
    write_pulse_us(SERVO_TEST_LOW_PULSE_TICKS);
    sweep_enabled = 1U;
}

void servo_update(uint32_t now_ms)
{
    uint32_t phase_ms;
    uint32_t pulse_us;

    if (!sweep_enabled || now_ms == last_sweep_ms) return;
    last_sweep_ms = now_ms;
    phase_ms = (now_ms - sweep_start_ms) % SERVO_TEST_PERIOD_MS;
    pulse_us = (phase_ms < SERVO_TEST_HOLD_MS) ?
        SERVO_TEST_LOW_PULSE_TICKS : SERVO_TEST_HIGH_PULSE_TICKS;
    write_pulse_us(pulse_us);
}

