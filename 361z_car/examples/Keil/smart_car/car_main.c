#include "ti_msp_dl_config.h"
#include "mid_debug_uart.h"
#include "mid_timer.h"
#include "uart_imu.h"
#include "encoder.h"
#include "motor.h"
#include "motion.h"
#include "command.h"
#include "odometry.h"
#include "oled.h"

static void send_int(int v)
{
    char buf[12];
    int i = 0;

    if (v < 0)
    {
        debug_uart_send_char('-');
        v = -v;
    }

    do
    {
        buf[i++] = (char)('0' + (v % 10));
        v /= 10;
    } while (v > 0);

    while (i > 0)
    {
        debug_uart_send_char(buf[--i]);
    }
}

static void send_fixed1(float v)
{
    int32_t x;

    if (v >= 0.0f) x = (int32_t)(v * 10.0f + 0.5f);
    else           x = (int32_t)(v * 10.0f - 0.5f);

    if (x < 0)
    {
        debug_uart_send_char('-');
        x = -x;
    }

    send_int((int)(x / 10));
    debug_uart_send_char('.');
    debug_uart_send_char((char)('0' + (x % 10)));
}

static void print_status(void)
{
    const OdomState *o = motion_get_odom();

    debug_uart_send_string("r=");
    send_fixed1(uart_imu_roll() * 57.2958f);
    debug_uart_send_string(" p=");
    send_fixed1(uart_imu_pitch() * 57.2958f);
    debug_uart_send_string(" y=");
    send_fixed1(uart_imu_yaw() * 57.2958f);

    debug_uart_send_string(" | x=");
    send_int((int)(o->x * 1000.0f));
    debug_uart_send_string(" y=");
    send_int((int)(o->y * 1000.0f));
    debug_uart_send_string(" th=");
    send_int((int)(o->theta * 57.2958f));

    debug_uart_send_string(" | vL=");
    send_int((int)(o->v_left * 1000.0f));
    debug_uart_send_string(" vR=");
    send_int((int)(o->v_right * 1000.0f));
    debug_uart_send_string("\r\n");
}

int main(void)
{
    uint8_t imu_started = 0;
    uint32_t last_lost_print = 0;
    uint32_t last_status_print = 0;

    SYSCFG_DL_init();

    debug_uart_init();
    debug_uart_set_baud_115200();

    uart_imu_init();
    encoder_init();
    motor_init();
    timer_init();

    motion_init();
    command_init();
    oled_show_hello();

    /* Keep the car still during power-on IMU calibration. */
    debug_uart_send_string("IMU CAL...\r\n");
    delay_cycles(CPUCLK_FREQ);
    uart_imu_calibrate();
    delay_cycles(CPUCLK_FREQ);
    uart_imu_set_report_rate(100);
    delay_cycles(CPUCLK_FREQ / 10);

    motor_enable(1);
    debug_uart_send_string("READY\r\n");

    while (1)
    {
        command_poll();

        if (uart_imu_poll())
        {
            imu_started = 1;
        }

        if (g_control_tick)
        {
            int left_delta;
            int right_delta;
            int imu_ok;

            g_control_tick = 0;

            encoder_update();
            left_delta = encoder_left_delta();
            right_delta = encoder_right_delta();
            imu_ok = uart_imu_online();

            if (command_active() == 1 &&
                (uint32_t)(g_ms_tick - command_last_tick()) > 2000)
            {
                command_clear_active();
                motion_stop();
                debug_uart_send_string("CMD_TIMEOUT\r\n");
            }

            motion_update(left_delta, right_delta, uart_imu_yaw(), imu_ok);

            if (imu_started && !imu_ok)
            {
                if ((uint32_t)(g_ms_tick - last_lost_print) >= 500)
                {
                    last_lost_print = g_ms_tick;
                    debug_uart_send_string("IMU_LOST\r\n");
                }
            }

            if ((uint32_t)(g_ms_tick - last_status_print) >= 100)
            {
                last_status_print = g_ms_tick;
                print_status();
            }
        }
    }
}
