#ifndef ODOMETRY_H
#define ODOMETRY_H

#include <stdint.h>

/* Calibrate these three values for your car. */
#define WHEEL_DIAMETER_M        0.085f
#define ENCODER_COUNTS_PER_REV  1456.0f
#define TRACK_WIDTH_M           0.1724f

#define ODOM_DT                 0.02f
#define METERS_PER_COUNT        (3.1415926f * WHEEL_DIAMETER_M / ENCODER_COUNTS_PER_REV)

typedef struct
{
    float x;
    float y;
    float theta;
    float v_left;
    float v_right;
} OdomState;

void odom_init(void);
void odom_reset(void);
void odom_update(int left_delta, int right_delta, float yaw_rad, int imu_ok);
const OdomState *odom_get(void);

#endif
