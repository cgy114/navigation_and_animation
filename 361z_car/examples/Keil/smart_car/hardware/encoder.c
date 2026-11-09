#include "encoder.h"
#include "ti_msp_dl_config.h"

#define ENC2_A_PIN       DL_GPIO_PIN_2
#define ENC2_B_PIN       DL_GPIO_PIN_3
#define ENC2_A_IOMUX     IOMUX_PINCM15
#define ENC2_B_IOMUX     IOMUX_PINCM16

static volatile int32_t left_temp = 0;
static volatile int32_t right_temp = 0;

static volatile int left_delta = 0;
static volatile int right_delta = 0;

static volatile int32_t left_total = 0;
static volatile int32_t right_total = 0;

void encoder_init(void)
{
    DL_GPIO_initDigitalInputFeatures(
        GPIO_ENCODER_PIN_A_IOMUX,
        DL_GPIO_INVERSION_DISABLE,
        DL_GPIO_RESISTOR_PULL_UP,
        DL_GPIO_HYSTERESIS_DISABLE,
        DL_GPIO_WAKEUP_DISABLE);

    DL_GPIO_initDigitalInputFeatures(
        GPIO_ENCODER_PIN_B_IOMUX,
        DL_GPIO_INVERSION_DISABLE,
        DL_GPIO_RESISTOR_PULL_UP,
        DL_GPIO_HYSTERESIS_DISABLE,
        DL_GPIO_WAKEUP_DISABLE);

    DL_GPIO_initDigitalInputFeatures(
        ENC2_A_IOMUX,
        DL_GPIO_INVERSION_DISABLE,
        DL_GPIO_RESISTOR_PULL_UP,
        DL_GPIO_HYSTERESIS_DISABLE,
        DL_GPIO_WAKEUP_DISABLE);

    DL_GPIO_initDigitalInputFeatures(
        ENC2_B_IOMUX,
        DL_GPIO_INVERSION_DISABLE,
        DL_GPIO_RESISTOR_PULL_UP,
        DL_GPIO_HYSTERESIS_DISABLE,
        DL_GPIO_WAKEUP_DISABLE);

    /* PB0..PB3: count both edges (4x quadrature decoding). */
    DL_GPIO_setLowerPinsPolarity(
        GPIOB,
        DL_GPIO_PIN_0_EDGE_RISE_FALL |
        DL_GPIO_PIN_1_EDGE_RISE_FALL |
        DL_GPIO_PIN_2_EDGE_RISE_FALL |
        DL_GPIO_PIN_3_EDGE_RISE_FALL);

    DL_GPIO_clearInterruptStatus(
        GPIOB,
        GPIO_ENCODER_PIN_A_PIN |
        GPIO_ENCODER_PIN_B_PIN |
        ENC2_A_PIN |
        ENC2_B_PIN);

    DL_GPIO_enableInterrupt(
        GPIOB,
        GPIO_ENCODER_PIN_A_PIN |
        GPIO_ENCODER_PIN_B_PIN |
        ENC2_A_PIN |
        ENC2_B_PIN);

    NVIC_ClearPendingIRQ(GPIOB_INT_IRQn);
    NVIC_EnableIRQ(GPIOB_INT_IRQn);
}

void GROUP1_IRQHandler(void)
{
    uint32_t status = DL_GPIO_getEnabledInterruptStatus(
        GPIOB,
        GPIO_ENCODER_PIN_A_PIN |
        GPIO_ENCODER_PIN_B_PIN |
        ENC2_A_PIN |
        ENC2_B_PIN);
    int a;
    int b;

    /* 4x decoding: every edge of both channels is counted once.
     *
     * A edge advances when A and B differ, B edge advances when they
     * are equal. Both rules keep the direction sign of the old code.
     */
    if (status & (GPIO_ENCODER_PIN_A_PIN | GPIO_ENCODER_PIN_B_PIN))
    {
        a = DL_GPIO_readPins(GPIOB, GPIO_ENCODER_PIN_A_PIN) ? 1 : 0;
        b = DL_GPIO_readPins(GPIOB, GPIO_ENCODER_PIN_B_PIN) ? 1 : 0;

        if (status & GPIO_ENCODER_PIN_A_PIN)
            left_temp += (a != b) ? -1 : 1;

        if (status & GPIO_ENCODER_PIN_B_PIN)
            left_temp += (a != b) ? 1 : -1;
    }

    if (status & (ENC2_A_PIN | ENC2_B_PIN))
    {
        a = DL_GPIO_readPins(GPIOB, ENC2_A_PIN) ? 1 : 0;
        b = DL_GPIO_readPins(GPIOB, ENC2_B_PIN) ? 1 : 0;

        if (status & ENC2_A_PIN)
            right_temp += (a != b) ? -1 : 1;

        if (status & ENC2_B_PIN)
            right_temp += (a != b) ? 1 : -1;
    }

    DL_GPIO_clearInterruptStatus(GPIOB, status);
}

void encoder_update(void)
{
    uint32_t primask = __get_PRIMASK();

    __disable_irq();
    left_delta = left_temp;
    right_delta = right_temp;
    left_temp = 0;
    right_temp = 0;
    left_total += left_delta;
    right_total += right_delta;
    __set_PRIMASK(primask);
}

void encoder_reset_totals(void)
{
    uint32_t primask = __get_PRIMASK();

    __disable_irq();
    left_temp = 0;
    right_temp = 0;
    left_delta = 0;
    right_delta = 0;
    left_total = 0;
    right_total = 0;
    __set_PRIMASK(primask);
}

int encoder_left_delta(void)  { return left_delta; }
int encoder_right_delta(void) { return right_delta; }

int32_t encoder_left_total(void)  { return left_total; }
int32_t encoder_right_total(void) { return right_total; }
