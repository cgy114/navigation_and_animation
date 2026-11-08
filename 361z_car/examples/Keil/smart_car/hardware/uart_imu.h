#ifndef UART_IMU_H
#define UART_IMU_H

#include <stdint.h>

void uart_imu_init(void);
int  uart_imu_poll(void);
int  uart_imu_online(void);
float uart_imu_roll(void);
float uart_imu_pitch(void);
float uart_imu_yaw(void);

void uart_imu_set_report_rate(uint8_t rate);
void uart_imu_set_algo(uint8_t algo);
void uart_imu_calibrate(void);

#endif
