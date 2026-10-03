/* SPDX-License-Identifier: GPL-2.0 */
/*
 * MSM8953 CPU voltage control (cpufreq UV_mV_table attribute).
 */

#ifndef __LINUX_CLK_MSM8953_CPU_UV_H__
#define __LINUX_CLK_MSM8953_CPU_UV_H__

#ifdef CONFIG_MSM8953_CPU_VOLTAGE_CONTROL
struct freq_attr;

extern struct freq_attr msm8953_uv_mv_table;
#endif

#endif /* __LINUX_CLK_MSM8953_CPU_UV_H__ */
