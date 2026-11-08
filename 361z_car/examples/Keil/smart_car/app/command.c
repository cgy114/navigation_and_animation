#include "command.h"
#include "mid_debug_uart.h"
#include "mid_timer.h"
#include "motion.h"
#include "odometry.h"
#include "encoder.h"

static char line[64];
static uint8_t line_len = 0;
static uint32_t last_cmd_tick = 0;
static uint8_t active = 0;

static void print_help(void)
{
    debug_uart_send_string(
        "Commands:\r\n"
        "  M <v_mm_s> <w_mrad_s>  move (2s timeout)\r\n"
        "  G <v_mm_s> <w_mrad_s>  move continuous\r\n"
        "  S                      stop\r\n"
        "  R                      reset odom + encoder counts\r\n"
        "  E                      show encoder totals\r\n"
        "  P <kp> <ki> <kd>       PID gains\r\n"
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

static int parse_int(const char **pp, int *out)
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
        value = value * 10 + (*p - '0');
        p++;
        digits++;
    }

    if (!digits) return 0;
    *out = sign * value;
    *pp = p;
    return 1;
}

static void handle_line(char *s)
{
    char *p = s;
    const char *q;
    int a, b, c;

    while (*p == ' ' || *p == '\t') p++;

    if (*p == 'M' || *p == 'm' || *p == 'G' || *p == 'g')
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
        if (parse_int(&q, &a) &&
            parse_int(&q, &b) &&
            parse_int(&q, &c))
        {
            motion_set_pid((float)a, (float)b, (float)c);
            debug_uart_send_string("OK P\r\n");
        }
        else
        {
            debug_uart_send_string("ERR P\r\n");
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

void command_init(void)
{
    line_len = 0;
    last_cmd_tick = 0;
    active = 0;
    print_help();
}

void command_poll(void)
{
    char c;

    while (debug_uart_get_char(&c))
    {
        if (c == '\r') continue;

        if (c == '\n')
        {
            line[line_len] = 0;
            handle_line(line);
            line_len = 0;
        }
        else if (line_len < sizeof(line) - 1)
        {
            line[line_len++] = c;
        }
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
