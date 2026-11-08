#include "uart_imu.h"
#include "ti_msp_dl_config.h"
#include "mid_timer.h"
#include <string.h>

#define RX_BUF_SIZE 128
#define FRAME_MAX   32
#define IMU_TIMEOUT_MS 200

static volatile uint8_t rx_buf[RX_BUF_SIZE];
static volatile uint16_t rx_head = 0;
static volatile uint16_t rx_tail = 0;

static uint8_t frame[FRAME_MAX];
static uint8_t frame_idx = 0;
static uint8_t frame_len = 0;

static float roll_rad = 0.0f;
static float pitch_rad = 0.0f;
static float yaw_rad = 0.0f;

static uint32_t last_rx_tick = 0;
static uint8_t  seen_frame = 0;

static void uart_imu_send_cmd(uint8_t func, uint8_t param)
{
    uint8_t cmd[7] = {0x7E, 0x23, 0x07, func, param, 0x5F, 0};
    uint8_t i;
    uint8_t sum = 0;

    for (i = 0; i < 6; i++) sum += cmd[i];
    cmd[6] = sum;

    for (i = 0; i < 7; i++)
    {
        while (DL_UART_isBusy(UART1));
        DL_UART_Main_transmitData(UART1, cmd[i]);
    }
}

void uart_imu_set_report_rate(uint8_t rate)
{
    if (rate < 10)  rate = 10;
    if (rate > 100) rate = 100;
    uart_imu_send_cmd(0x60, rate);
}

void uart_imu_set_algo(uint8_t algo)
{
    if (algo == 6 || algo == 9)
        uart_imu_send_cmd(0x61, algo);
}

void uart_imu_calibrate(void)
{
    uart_imu_send_cmd(0x70, 0x01);
}

void uart_imu_init(void)
{
    DL_UART_Main_reset(UART1);
    DL_UART_Main_enablePower(UART1);

    DL_GPIO_initPeripheralOutputFunction(IOMUX_PINCM23, IOMUX_PINCM23_PF_UART1_TX);
    DL_GPIO_initPeripheralInputFunction(IOMUX_PINCM24, IOMUX_PINCM24_PF_UART1_RX);

    static const DL_UART_Main_ClockConfig clock_cfg = {
        .clockSel    = DL_UART_MAIN_CLOCK_BUSCLK,
        .divideRatio = DL_UART_MAIN_CLOCK_DIVIDE_RATIO_1
    };
    static const DL_UART_Main_Config cfg = {
        .mode        = DL_UART_MAIN_MODE_NORMAL,
        .direction   = DL_UART_MAIN_DIRECTION_TX_RX,
        .flowControl = DL_UART_MAIN_FLOW_CONTROL_NONE,
        .parity      = DL_UART_MAIN_PARITY_NONE,
        .wordLength  = DL_UART_MAIN_WORD_LENGTH_8_BITS,
        .stopBits    = DL_UART_MAIN_STOP_BITS_ONE
    };

    DL_UART_Main_setClockConfig(UART1, (DL_UART_Main_ClockConfig *)&clock_cfg);
    DL_UART_Main_init(UART1, (DL_UART_Main_Config *)&cfg);

    /* 40 MHz BUSCLK, 16x oversampling, 115200 baud */
    DL_UART_Main_setOversampling(UART1, DL_UART_OVERSAMPLING_RATE_16X);
    DL_UART_Main_setBaudRateDivisor(UART1, 21, 45);

    DL_UART_Main_enableInterrupt(UART1, DL_UART_MAIN_INTERRUPT_RX);
    DL_UART_Main_enable(UART1);

    NVIC_ClearPendingIRQ(UART1_INT_IRQn);
    NVIC_EnableIRQ(UART1_INT_IRQn);

    delay_cycles(CPUCLK_FREQ / 10);

    uart_imu_set_algo(9);
    delay_cycles(CPUCLK_FREQ / 5);
    uart_imu_set_report_rate(100);
    delay_cycles(CPUCLK_FREQ / 10);
}

void UART1_IRQHandler(void)
{
    if (DL_UART_Main_getPendingInterrupt(UART1) == DL_UART_IIDX_RX)
    {
        uint8_t b = DL_UART_Main_receiveData(UART1);
        uint16_t next = (rx_head + 1) % RX_BUF_SIZE;
        if (next != rx_tail)
        {
            rx_buf[rx_head] = b;
            rx_head = next;
        }
    }
}

static int pop_byte(uint8_t *b)
{
    if (rx_tail == rx_head) return 0;
    *b = rx_buf[rx_tail];
    rx_tail = (rx_tail + 1) % RX_BUF_SIZE;
    return 1;
}

int uart_imu_poll(void)
{
    uint8_t b;
    int got = 0;

    while (pop_byte(&b))
    {
        if (frame_idx == 0)
        {
            if (b == 0x7E) frame[frame_idx++] = b;
        }
        else if (frame_idx == 1)
        {
            if (b == 0x23) frame[frame_idx++] = b;
            else frame_idx = 0;
        }
        else if (frame_idx == 2)
        {
            frame_len = b;
            if (frame_len >= 5 && frame_len <= FRAME_MAX)
                frame[frame_idx++] = b;
            else
                frame_idx = 0;
        }
        else
        {
            frame[frame_idx++] = b;
            if (frame_idx >= frame_len)
            {
                uint8_t sum = 0;
                uint8_t i;
                for (i = 0; i < frame_len - 1; i++) sum += frame[i];

                if (sum == frame[frame_len - 1] && frame[3] == 0x26 && frame_len == 17)
                {
                    memcpy(&roll_rad,  &frame[4],  4);
                    memcpy(&pitch_rad, &frame[8],  4);
                    memcpy(&yaw_rad,   &frame[12], 4);
                    last_rx_tick = g_ms_tick;
                    seen_frame = 1;
                    got = 1;
                }
                frame_idx = 0;
            }
        }
    }
    return got;
}

int uart_imu_online(void)
{
    if (!seen_frame) return 0;
    return (uint32_t)(g_ms_tick - last_rx_tick) < IMU_TIMEOUT_MS;
}

float uart_imu_roll(void)  { return roll_rad; }
float uart_imu_pitch(void) { return pitch_rad; }
float uart_imu_yaw(void)   { return yaw_rad; }
