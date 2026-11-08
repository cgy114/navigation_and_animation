#include "odometry.h"
#include <math.h>

static OdomState odom;
static float yaw_offset = 0.0f;
static int yaw_offset_valid = 0;

void odom_init(void)
{
    odom.x = 0.0f;
    odom.y = 0.0f;
    odom.theta = 0.0f;
    odom.v_left = 0.0f;
    odom.v_right = 0.0f;
    yaw_offset = 0.0f;
    yaw_offset_valid = 0;
}

void odom_reset(void)
{
    odom_init();
}

void odom_update(int left_delta, int right_delta, float yaw_rad, int imu_ok)
{
    float dl = (float)left_delta * METERS_PER_COUNT;
    float dr = (float)right_delta * METERS_PER_COUNT;
    float ds = (dl + dr) * 0.5f;
    float dth = (dr - dl) / TRACK_WIDTH_M;

    odom.v_left = dl / ODOM_DT;
    odom.v_right = dr / ODOM_DT;

    if (imu_ok)
    {
        if (!yaw_offset_valid)
        {
            yaw_offset = yaw_rad;
            yaw_offset_valid = 1;
        }
        odom.theta = yaw_rad - yaw_offset;
    }
    else
    {
        odom.theta += dth;
    }

    odom.x += ds * cosf(odom.theta);
    odom.y += ds * sinf(odom.theta);
}

const OdomState *odom_get(void)
{
    return &odom;
}
