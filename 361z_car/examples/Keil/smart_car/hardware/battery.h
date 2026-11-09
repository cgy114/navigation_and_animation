#ifndef BATTERY_H
#define BATTERY_H

#include <stdint.h>

/* PA25 / ADC0.A2. Reference is the MCU analog supply, nominally 3.3 V. */
#define BATTERY_ADC_REFERENCE_MV 3300U

/* Vbattery = Vpin * NUMERATOR / DENOMINATOR.
 * WHEELTEC D153B documentation specifies 10k/1k (x11). D153C uses this
 * same-series value provisionally; verify against a voltmeter on this board.
 * Set numerator to zero to report only the ADC pin voltage until calibrated. */
#define BATTERY_DIVIDER_NUMERATOR 11U
#define BATTERY_DIVIDER_DENOMINATOR 1U

void battery_init(void);
void battery_poll(uint32_t now_ms);
int battery_get_raw(uint16_t *raw);
int battery_get_adc_mv(uint32_t *millivolts);
int battery_get_voltage_mv(uint32_t *millivolts);

#endif
