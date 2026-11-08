#ifndef MOTION_H
#define MOTION_H

#include "odometry.h"

void motion_init(void);
void motion_set_target(float v_mps, float w_radps);
void motion_stop(void);
void motion_update(int left_delta, int right_delta, float yaw_rad, int imu_ok);
void motion_set_pid(float kp, float ki, float kd);
const OdomState *motion_get_odom(void);

#endif
