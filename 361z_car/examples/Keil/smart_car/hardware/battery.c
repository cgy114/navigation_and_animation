#include "battery.h"
#include "ti_msp_dl_config.h"

#define BATTERY_ADC ADC0
#define BATTERY_SAMPLE_INTERVAL_MS 20U
#define BATTERY_CONVERSION_TIMEOUT_MS 20U
#define BATTERY_FILTER_SAMPLES 8U
#define BATTERY_ADC_MAX 4095U

static uint16_t samples[BATTERY_FILTER_SAMPLES];
static uint32_t sample_sum;
static uint32_t sample_started_ms;
static uint8_t sample_count;
static uint8_t sample_index;
static uint8_t conversion_pending;
static uint8_t reading_valid;

void battery_init(void)
{
    DL_ADC12_ClockConfig clock_config = {
        .clockSel = DL_ADC12_CLOCK_SYSOSC,
        .freqRange = DL_ADC12_CLOCK_FREQ_RANGE_24_TO_32,
        .divideRatio = DL_ADC12_CLOCK_DIVIDE_8
    };

    sample_sum = 0U;
    sample_count = 0U;
    sample_index = 0U;
    sample_started_ms = 0U;
    reading_valid = 0U;

    DL_ADC12_reset(BATTERY_ADC);
    DL_ADC12_enablePower(BATTERY_ADC);
    delay_cycles(POWER_STARTUP_DELAY);
    DL_GPIO_initPeripheralAnalogFunction(IOMUX_PINCM55); /* PA25 / ADC0.A2 */
    DL_ADC12_setClockConfig(BATTERY_ADC, &clock_config);
    DL_ADC12_initSingleSample(BATTERY_ADC,
        DL_ADC12_REPEAT_MODE_DISABLED, DL_ADC12_SAMPLING_SOURCE_AUTO,
        DL_ADC12_TRIG_SRC_SOFTWARE, DL_ADC12_SAMP_CONV_RES_12_BIT,
        DL_ADC12_SAMP_CONV_DATA_FORMAT_UNSIGNED);
    DL_ADC12_configConversionMem(BATTERY_ADC, DL_ADC12_MEM_IDX_0,
        DL_ADC12_INPUT_CHAN_2, DL_ADC12_REFERENCE_VOLTAGE_VDDA,
        DL_ADC12_SAMPLE_TIMER_SOURCE_SCOMP0, DL_ADC12_AVERAGING_MODE_DISABLED,
        DL_ADC12_BURN_OUT_SOURCE_DISABLED, DL_ADC12_TRIGGER_MODE_AUTO_NEXT,
        DL_ADC12_WINDOWS_COMP_MODE_DISABLED);
    DL_ADC12_setPowerDownMode(BATTERY_ADC, DL_ADC12_POWER_DOWN_MODE_MANUAL);
    /* 32 MHz SYSOSC / 8 = 4 MHz sample clock; 500 cycles = 125 us.
     * Long acquisition time accommodates a resistive battery divider. */
    DL_ADC12_setSampleTime0(BATTERY_ADC, 500U);
    DL_ADC12_clearInterruptStatus(BATTERY_ADC, DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED);
    DL_ADC12_enableConversions(BATTERY_ADC);
    DL_ADC12_startConversion(BATTERY_ADC);
    conversion_pending = 1U;
}

void battery_poll(uint32_t now_ms)
{
    if (conversion_pending)
    {
        if (DL_ADC12_getRawInterruptStatus(BATTERY_ADC,
                DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED))
        {
            uint16_t raw = DL_ADC12_getMemResult(BATTERY_ADC, DL_ADC12_MEM_IDX_0);
            DL_ADC12_clearInterruptStatus(BATTERY_ADC,
                DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED);
            if (sample_count == BATTERY_FILTER_SAMPLES)
                sample_sum -= samples[sample_index];
            else
                sample_count++;
            samples[sample_index] = raw;
            sample_sum += raw;
            sample_index = (uint8_t)((sample_index + 1U) % BATTERY_FILTER_SAMPLES);
            reading_valid = 1U;
            conversion_pending = 0U;
        }
        else if ((uint32_t)(now_ms - sample_started_ms) >= BATTERY_CONVERSION_TIMEOUT_MS)
        {
            /* Do not let a failed ADC conversion block motor/serial processing. */
            DL_ADC12_stopConversion(BATTERY_ADC);
            DL_ADC12_disableConversions(BATTERY_ADC);
            DL_ADC12_enableConversions(BATTERY_ADC);
            reading_valid = 0U;
            sample_sum = 0U;
            sample_count = 0U;
            sample_index = 0U;
            conversion_pending = 0U;
        }
    }

    if (!conversion_pending &&
        (uint32_t)(now_ms - sample_started_ms) >= BATTERY_SAMPLE_INTERVAL_MS)
    {
        DL_ADC12_clearInterruptStatus(BATTERY_ADC,
            DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED);
        sample_started_ms = now_ms;
        conversion_pending = 1U;
        DL_ADC12_startConversion(BATTERY_ADC);
    }
}

int battery_get_raw(uint16_t *raw)
{
    if (!reading_valid || sample_count == 0U) return 0;
    *raw = (uint16_t)((sample_sum + sample_count / 2U) / sample_count);
    return 1;
}

int battery_get_adc_mv(uint32_t *millivolts)
{
    uint16_t raw;
    if (!battery_get_raw(&raw)) return 0;
    *millivolts = ((uint32_t)raw * BATTERY_ADC_REFERENCE_MV + BATTERY_ADC_MAX / 2U)
        / BATTERY_ADC_MAX;
    return 1;
}

int battery_get_voltage_mv(uint32_t *millivolts)
{
    uint16_t raw;
    uint32_t denominator = BATTERY_ADC_MAX * BATTERY_DIVIDER_DENOMINATOR;
    if (BATTERY_DIVIDER_NUMERATOR == 0U || !battery_get_raw(&raw)) return 0;
    *millivolts = (uint32_t)(((uint64_t)raw * BATTERY_ADC_REFERENCE_MV *
        BATTERY_DIVIDER_NUMERATOR + denominator / 2U) / denominator);
    return 1;
}
