#include "command.h"
#include "mid_debug_uart.h"
#include "mid_timer.h"
#include "motion.h"
#include "odometry.h"
#include "encoder.h"
#include "pid_store.h"
#include "servo.h"
#include "battery.h"
#include "uart_pi.h"

typedef struct
{
    char line[64];
    uint8_t length;
    uint8_t overflow;
} CommandLine;

static CommandLine debug_line;
static CommandLine pi_line;
static uint32_t last_cmd_tick = 0;
static uint8_t active = 0;

/* Signed PWM out of 10000; positive means physical wheel forward. */
#define WHEEL_TEST_PWM 3000

static void handle_wheel_command(char command)
{
    active = 0;
    switch (command)
    {
        case '0': motion_stop(); break;
        case '1': motion_set_direct_pwm( WHEEL_TEST_PWM,  WHEEL_TEST_PWM); break;
        case '2': motion_set_direct_pwm(-WHEEL_TEST_PWM, -WHEEL_TEST_PWM); break;
        case '3': motion_set_direct_pwm( WHEEL_TEST_PWM, -WHEEL_TEST_PWM); break;
        case '4': motion_set_direct_pwm(-WHEEL_TEST_PWM,  WHEEL_TEST_PWM); break;
        default: return;
    }
    debug_uart_send_string("OK ");
    debug_uart_send_char(command);
    debug_uart_send_string("\r\n");
}

static void print_help(void)
{
    debug_uart_send_string(
        "Commands:\r\n"
        "  1/2                    both wheels forward/backward\r\n"
        "  3/4                    left forward/right backward, or reverse\r\n"
        "  0                      stop both wheels\r\n"
        "  center                 PA15 servo\r\n"
        "                         1500us high / 20000us period (boot)\r\n"
        "  sweep                  left 1300us 1s / right 1700us 1s\r\n"
        "  on / off               right 1700us / left 1300us\r\n"
        "  D <pulse_us>           set servo pulse width (1000..2000 us)\r\n"
        "  B?                     show PA25 ADC raw/pin/battery millivolts\r\n"
        "  M <v_mm_s> <w_mrad_s>  move (2s timeout)\r\n"
        "  G <v_mm_s> <w_mrad_s>  move continuous\r\n"
        "  S                      stop\r\n"
        "  R                      reset odom + encoder counts\r\n"
        "  E                      show encoder totals\r\n"
        "  P?                     show RAM and Flash PID gains\r\n"
        "  P <pwm>                direct both wheels (-10000..10000)\r\n"
        "  P <kp> <ki> <kd>       set RAM PID gains (0..100000)\r\n"
        "  PS / PL / PD           save Flash / load Flash / RAM defaults\r\n"
        "  ?                      help\r\n"
        "Example: M 300 0\r\n");
}

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

/* ArmClang 6.7 at -O2 miscompiles the whitespace/sign dispatch when this
 * parser is inlined repeatedly into handle_line: a jump-table base register
 * is overwritten before it is read. Keep the parser as a separate function.
 * tests/test_command_arm.py exercises the final ARM binary, not a host build. */
static __attribute__((noinline)) int parse_int(const char **pp, int *out)
{
    const char *p = *pp;
    int sign = 1;
    int value = 0;
    int digits = 0;

    while (*p == ' ' || *p == '\t') p++;
    if (*p == '-') { sign = -1; p++; }
    else if (*p == '+') { p++; }

    while (*p >= '0' && *p <= '9')
    {
        if (value > 100000) return 0;
        value = value * 10 + (*p - '0');
        p++;
        digits++;
    }

    if (!digits) return 0;
    *out = sign * value;
    *pp = p;
    return 1;
}

static int at_end(const char *p)
{
    while (*p == ' ' || *p == '\t') ++p;
    return *p == 0;
}

static int command_is(const char *text, const char *word)
{
    while (*word) {
        char c = *text++;
        if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
        if (c != *word++) return 0;
    }
    return at_end(text);
}

static void print_pid_status(void)
{
    float kp, ki, kd;
    PidGains flash;
    motion_get_pid(&kp, &ki, &kd);
    debug_uart_send_string("PID RAM ");
    send_int((int)kp); debug_uart_send_char(' ');
    send_int((int)ki); debug_uart_send_char(' ');
    send_int((int)kd);
    debug_uart_send_string(" FLASH ");
    if (pid_store_load(&flash)) {
        send_int((int)flash.kp); debug_uart_send_char(' ');
        send_int((int)flash.ki); debug_uart_send_char(' ');
        send_int((int)flash.kd);
    } else {
        debug_uart_send_string("NONE");
    }
    debug_uart_send_string("\r\n");
}

static void handle_line(char *s)
{
    char *p = s;
    const char *q;
    int a, b, c;

    while (*p == ' ' || *p == '\t') p++;

    if (command_is(p, "b?"))
    {
        uint16_t raw;
        uint32_t pin_mv;
        uint32_t battery_mv;
        if (battery_get_raw(&raw) && battery_get_adc_mv(&pin_mv))
        {
            debug_uart_send_string("BAT raw=");
            send_int(raw);
            debug_uart_send_string(" adc_mv=");
            send_int((int)pin_mv);
            debug_uart_send_string(" battery_mv=");
            if (battery_get_voltage_mv(&battery_mv))
                send_int((int)battery_mv);
            else
                debug_uart_send_string("UNCAL");
            debug_uart_send_string("\r\n");
        }
        else
        {
            debug_uart_send_string("ERR B ADC\r\n");
        }
    }
    else if (command_is(p, "center"))
    {
        servo_set_pulse_us(SERVO_CENTER_PULSE_US);
        debug_uart_send_string("OK CENTER\r\n");
    }
    else if (command_is(p, "sweep"))
    {
        servo_start_sweep(g_ms_tick);
        debug_uart_send_string("OK SWEEP\r\n");
    }
    else if (command_is(p, "on"))
    {
        servo_set_pulse_us(SERVO_RIGHT_PULSE_US);
        debug_uart_send_string("OK ON\r\n");
    }
    else if (command_is(p, "off"))
    {
        servo_set_pulse_us(SERVO_LEFT_PULSE_US);
        debug_uart_send_string("OK OFF\r\n");
    }
    else if (*p == 'D' || *p == 'd')
    {
        q = p + 1;
        if (parse_int(&q, &a) && at_end(q) &&
            a >= (int)SERVO_MIN_PULSE_US && a <= (int)SERVO_MAX_PULSE_US)
        {
            servo_set_pulse_us((unsigned)a);
            debug_uart_send_string("OK D\r\n");
        }
        else
        {
            debug_uart_send_string("ERR D\r\n");
        }
    }
    else if (*p == 'M' || *p == 'm' || *p == 'G' || *p == 'g')
    {
        int continuous = (*p == 'G' || *p == 'g');
        q = p + 1;
        if (parse_int(&q, &a) &&
            parse_int(&q, &b))
        {
            motion_set_target((float)a / 1000.0f, (float)b / 1000.0f);
            last_cmd_tick = g_ms_tick;
            active = continuous ? 2 : 1;
            debug_uart_send_string(continuous ? "OK G\r\n" : "OK M\r\n");
        }
        else
        {
            debug_uart_send_string("ERR M\r\n");
        }
    }
    else if (*p == 'S' || *p == 's')
    {
        motion_stop();
        active = 0;
        debug_uart_send_string("OK S\r\n");
    }
    else if (*p == 'R' || *p == 'r')
    {
        odom_reset();
        encoder_reset_totals();
        debug_uart_send_string("OK R\r\n");
    }
    else if (*p == 'E' || *p == 'e')
    {
        debug_uart_send_string("ENC L=");
        send_int((int)encoder_left_total());
        debug_uart_send_string(" R=");
        send_int((int)encoder_right_total());
        debug_uart_send_string("\r\n");
    }
    else if (*p == 'P' || *p == 'p')
    {
        q = p + 1;
        if (*q == '?' && at_end(q + 1)) {
            debug_uart_send_string("PID QUERY\r\n");
            print_pid_status();
        } else if ((*q == 'S' || *q == 's') && at_end(q + 1)) {
            PidGains gains;
            float kp, ki, kd;
            motion_get_pid(&kp, &ki, &kd);
            gains.kp = (int32_t)kp; gains.ki = (int32_t)ki; gains.kd = (int32_t)kd;
            motion_stop();
            active = 0;
            debug_uart_send_string(pid_store_save(&gains) ? "OK PS\r\n" : "ERR PS\r\n");
            print_pid_status();
        } else if ((*q == 'L' || *q == 'l') && at_end(q + 1)) {
            PidGains gains;
            if (pid_store_load(&gains)) {
                motion_set_pid((float)gains.kp, (float)gains.ki, (float)gains.kd);
                debug_uart_send_string("OK PL\r\n");
            } else {
                debug_uart_send_string("ERR PL\r\n");
            }
            print_pid_status();
        } else if ((*q == 'D' || *q == 'd') && at_end(q + 1)) {
            PidGains gains;
            pid_store_defaults(&gains);
            motion_set_pid((float)gains.kp, (float)gains.ki, (float)gains.kd);
            debug_uart_send_string("OK PD\r\n");
            print_pid_status();
        } else {
            const char *single = q;
            if (parse_int(&single, &a) && at_end(single)) {
                if (a >= -10000 && a <= 10000) {
                    active = 0;
                    motion_set_direct_pwm(a, a);
                    debug_uart_send_string("OK P PWM\r\n");
                } else {
                    debug_uart_send_string("ERR P PWM\r\n");
                }
            } else if (parse_int(&q, &a) &&
                       parse_int(&q, &b) &&
                       parse_int(&q, &c) && at_end(q))
            {
                PidGains gains;
                gains.kp = a; gains.ki = b; gains.kd = c;
                if (pid_store_valid_gains(&gains)) {
                    motion_set_pid((float)a, (float)b, (float)c);
                    debug_uart_send_string("OK P\r\n");
                    print_pid_status();
                } else {
                    debug_uart_send_string("ERR P\r\n");
                }
            } else {
                debug_uart_send_string("ERR P\r\n");
            }
        }
    }
    else if (*p == '?')
    {
        print_help();
    }
    else if (*p != 0)
    {
        debug_uart_send_string("ERR CMD\r\n");
    }
}

/* Short commands must work even when the terminal sends no line ending. */
static void dispatch_short_command(CommandLine *input)
{
    input->line[input->length] = 0;
    if (command_is(input->line, "on") || command_is(input->line, "off") ||
        command_is(input->line, "p?") || command_is(input->line, "ps") ||
        command_is(input->line, "pl") || command_is(input->line, "pd") ||
        command_is(input->line, "sweep") || command_is(input->line, "center") ||
        command_is(input->line, "b?"))
    {
        handle_line(input->line);
        input->length = 0;
    }
}

void command_init(void)
{
    debug_line.length = 0;
    debug_line.overflow = 0;
    pi_line.length = 0;
    pi_line.overflow = 0;
    last_cmd_tick = 0;
    active = 0;
    print_help();
}

static void process_char(CommandLine *input, char c)
{
    if (c == '\r' || c == '\n')
    {
        if (input->overflow)
        {
            debug_uart_send_string("ERR LINE\r\n");
        }
        else if (input->length != 0)
        {
            input->line[input->length] = 0;
            handle_line(input->line);
        }
        input->length = 0;
        input->overflow = 0;
        return;
    }

    if (input->overflow) return;

    /* Single digits work immediately, with or without a trailing newline. */
    if (input->length == 0 && c >= '0' && c <= '4')
    {
        handle_wheel_command(c);
        return;
    }

    if (input->length >= sizeof(input->line) - 1)
    {
        input->overflow = 1;
        return;
    }

    input->line[input->length++] = c;
    dispatch_short_command(input);
}

void command_poll(void)
{
    char c;

    while (debug_uart_get_char(&c))
    {
        process_char(&debug_line, c);
    }
    while (uart_pi_get_char(&c))
    {
        process_char(&pi_line, c);
    }
}

uint32_t command_last_tick(void)
{
    return last_cmd_tick;
}

int command_active(void)
{
    return active;
}

void command_clear_active(void)
{
    active = 0;
}
