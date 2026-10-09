// SPDX-License-Identifier: GPL-2.0-only
/* drivers/cpufreq/qcom-cpufreq.c
 *
 * MSM architecture cpufreq driver
 *
 * Copyright (C) 2007 Google, Inc.
 * Copyright (c) 2007-2020, The Linux Foundation. All rights reserved.
 * Author: Mike A. Chan <mikechan@google.com>
 *
 */

#include <linux/init.h>
#include <linux/module.h>
#include <linux/cpufreq.h>
#include <linux/cpu.h>
#include <linux/cpumask.h>
#include <linux/suspend.h>
#include <linux/clk.h>
#include <linux/clk/msm8953-cpu-uv.h>
#include <linux/err.h>
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/of_device.h>
#include <linux/cpu_cooling.h>
#include <trace/events/power.h>
#include <linux/fb.h>
#include <linux/notifier.h>
#include <linux/workqueue.h>

static DEFINE_MUTEX(l2bw_lock);

static struct thermal_cooling_device *cdev[NR_CPUS];
static struct clk *cpu_clk[NR_CPUS];
static struct clk *l2_clk;
static DEFINE_PER_CPU(struct cpufreq_frequency_table *, freq_table);
static bool hotplug_ready;

struct cpufreq_suspend_t {
	struct mutex suspend_mutex;
	int device_suspended;
};

static DEFINE_PER_CPU(struct cpufreq_suspend_t, suspend_data);
static DEFINE_PER_CPU(int, cached_resolve_idx);
static DEFINE_PER_CPU(unsigned int, cached_resolve_freq);

static int set_cpu_freq(struct cpufreq_policy *policy, unsigned int new_freq,
			unsigned int index)
{
	int ret = 0;
	struct cpufreq_freqs freqs;
	unsigned long rate;

	freqs.old = policy->cur;
	freqs.new = new_freq;
	freqs.cpu = policy->cpu;

	trace_cpu_frequency_switch_start(freqs.old, freqs.new, policy->cpu);
	cpufreq_freq_transition_begin(policy, &freqs);

	rate = new_freq * 1000;
	rate = clk_round_rate(cpu_clk[policy->cpu], rate);
	ret = clk_set_rate(cpu_clk[policy->cpu], rate);
	cpufreq_freq_transition_end(policy, &freqs, ret);
	if (!ret) {
		arch_set_freq_scale(policy->related_cpus, new_freq,
				    policy->cpuinfo.max_freq);
		trace_cpu_frequency_switch_end(policy->cpu);
	}

	return ret;
}

static int msm_cpufreq_target(struct cpufreq_policy *policy,
				unsigned int target_freq,
				unsigned int relation)
{
	int ret = 0;
	int index;
	struct cpufreq_frequency_table *table;
	int first_cpu = cpumask_first(policy->related_cpus);

	mutex_lock(&per_cpu(suspend_data, policy->cpu).suspend_mutex);

	if (target_freq == policy->cur)
		goto done;

	if (per_cpu(suspend_data, policy->cpu).device_suspended) {
		pr_debug("cpufreq: cpu%d scheduling frequency change in suspend\n",
			 policy->cpu);
		ret = -EFAULT;
		goto done;
	}

	table = policy->freq_table;
	if (per_cpu(cached_resolve_freq, first_cpu) == target_freq)
		index = per_cpu(cached_resolve_idx, first_cpu);
	else
		index = cpufreq_frequency_table_target(policy, target_freq,
						       relation);

	pr_debug("CPU[%d] target %d relation %d (%d-%d) selected %d\n",
		policy->cpu, target_freq, relation,
		policy->min, policy->max, table[index].frequency);

	ret = set_cpu_freq(policy, table[index].frequency,
			   table[index].driver_data);
done:
	mutex_unlock(&per_cpu(suspend_data, policy->cpu).suspend_mutex);
	return ret;
}

static unsigned int msm_cpufreq_resolve_freq(struct cpufreq_policy *policy,
					     unsigned int target_freq)
{
	int index;
	int first_cpu = cpumask_first(policy->related_cpus);
	unsigned int freq;

	index = cpufreq_frequency_table_target(policy, target_freq,
					       CPUFREQ_RELATION_L);
	freq = policy->freq_table[index].frequency;

	per_cpu(cached_resolve_idx, first_cpu) = index;
	per_cpu(cached_resolve_freq, first_cpu) = freq;

	return freq;
}

static int msm_cpufreq_verify(struct cpufreq_policy *policy)
{
	cpufreq_verify_within_limits(policy, policy->cpuinfo.min_freq,
			policy->cpuinfo.max_freq);
	return 0;
}

static unsigned int msm_cpufreq_get_freq(unsigned int cpu)
{
	return clk_get_rate(cpu_clk[cpu]) / 1000;
}

static int msm_cpufreq_init(struct cpufreq_policy *policy)
{
	int cur_freq;
	int index;
	int ret = 0;
	struct cpufreq_frequency_table *table =
			per_cpu(freq_table, policy->cpu);
	int cpu;

	/*
	 * In some SoC, some cores are clocked by same source, and their
	 * frequencies can not be changed independently. Find all other
	 * CPUs that share same clock, and mark them as controlled by
	 * same policy.
	 */
	for_each_possible_cpu(cpu)
		if (cpu_clk[cpu] == cpu_clk[policy->cpu])
			cpumask_set_cpu(cpu, policy->cpus);

	policy->freq_table = table;
	ret = cpufreq_table_validate_and_sort(policy);
	if (ret) {
		pr_err("cpufreq: failed to get policy min/max\n");
		return ret;
	}

	cur_freq = clk_get_rate(cpu_clk[policy->cpu])/1000;

	index =  cpufreq_frequency_table_target(policy, cur_freq,
						CPUFREQ_RELATION_H);
	/*
	 * Call set_cpu_freq unconditionally so that when cpu is set to
	 * online, frequency limit will always be updated.
	 */
	ret = set_cpu_freq(policy, table[index].frequency,
			   table[index].driver_data);
	if (ret)
		return ret;
	pr_debug("cpufreq: cpu%d init at %d switching to %d\n",
			policy->cpu, cur_freq, table[index].frequency);
	policy->cur = table[index].frequency;
	policy->dvfs_possible_from_any_cpu = true;

	return 0;
}

static int qcom_cpufreq_dead_cpu(unsigned int cpu)
{
	/* Fail hotplug until this driver can get CPU clocks */
	if (!hotplug_ready)
		return -EINVAL;

	clk_unprepare(cpu_clk[cpu]);
	clk_unprepare(l2_clk);
	return 0;
}

static int qcom_cpufreq_up_cpu(unsigned int cpu)
{
	int rc;

	/* Fail hotplug until this driver can get CPU clocks */
	if (!hotplug_ready)
		return -EINVAL;

	rc = clk_prepare(l2_clk);
	if (rc < 0)
		return rc;
	rc = clk_prepare(cpu_clk[cpu]);
	if (rc < 0)
		clk_unprepare(l2_clk);
	return rc;
}

static int qcom_cpufreq_dying_cpu(unsigned int cpu)
{
	/* Fail hotplug until this driver can get CPU clocks */
	if (!hotplug_ready)
		return -EINVAL;

	clk_disable(cpu_clk[cpu]);
	clk_disable(l2_clk);
	return 0;
}

static int qcom_cpufreq_starting_cpu(unsigned int cpu)
{
	int rc;

	/* Fail hotplug until this driver can get CPU clocks */
	if (!hotplug_ready)
		return -EINVAL;

	rc = clk_enable(l2_clk);
	if (rc < 0)
		return rc;
	rc = clk_enable(cpu_clk[cpu]);
	if (rc < 0)
		clk_disable(l2_clk);
	return rc;
}

static int msm_cpufreq_suspend(void)
{
	int cpu;

	for_each_possible_cpu(cpu) {
		mutex_lock(&per_cpu(suspend_data, cpu).suspend_mutex);
		per_cpu(suspend_data, cpu).device_suspended = 1;
		mutex_unlock(&per_cpu(suspend_data, cpu).suspend_mutex);
	}

	return NOTIFY_DONE;
}

static int msm_cpufreq_resume(void)
{
	int cpu, ret;
	struct cpufreq_policy policy;

	for_each_possible_cpu(cpu) {
		per_cpu(suspend_data, cpu).device_suspended = 0;
	}

	/*
	 * Freq request might be rejected during suspend, resulting
	 * in policy->cur violating min/max constraint.
	 * Correct the frequency as soon as possible.
	 */
	get_online_cpus();
	for_each_online_cpu(cpu) {
		ret = cpufreq_get_policy(&policy, cpu);
		if (ret)
			continue;
		if (policy.cur <= policy.max && policy.cur >= policy.min)
			continue;
		cpufreq_update_policy(cpu);
	}
	put_online_cpus();

	return NOTIFY_DONE;
}

static int msm_cpufreq_pm_event(struct notifier_block *this,
				unsigned long event, void *ptr)
{
	switch (event) {
	case PM_POST_HIBERNATION:
	case PM_POST_SUSPEND:
		return msm_cpufreq_resume();
	case PM_HIBERNATION_PREPARE:
	case PM_SUSPEND_PREPARE:
		return msm_cpufreq_suspend();
	default:
		return NOTIFY_DONE;
	}
}

static struct notifier_block msm_cpufreq_pm_notifier = {
	.notifier_call = msm_cpufreq_pm_event,
};

/*
 * Screen-off frequency ceiling.
 *
 * Userspace wants the big cluster capped while the panel is dark, but must
 * not have to hold a frequency: the ceiling goes through the CPUFREQ_ADJUST
 * hook, so the governor keeps choosing inside [min, cap] exactly as it does
 * on screen-on. Only policy->max is touched, so a scaling_max_freq the user
 * set lower still wins, and waking the screen restores the hardware table
 * ceiling rather than some remembered value.
 *
 * The display reports blanking through the fb notifier chain
 * (drivers/video/fbdev/core/fbmem.c: fb_blank()). FB_EVENT_BLANK carries the
 * new blank mode in event->data, so one event covers both directions: any
 * mode other than FB_BLANK_UNBLANK caps, FB_BLANK_UNBLANK releases.
 */
static unsigned int screen_off_cap_khz = 1401600;

/* Written by the fb notifier, read by the CPUFREQ_ADJUST hook: WRITE_ONCE/READ_ONCE. */
static bool screen_off_capped;

/*
 * Re-evaluating policies must not run inside the fb notifier: that chain is
 * called from the display stack (composer holds mdp locks there), and
 * cpufreq_update_policy() takes the hotplug and policy locks. Doing it inline
 * deadlocked composer@2.1-se in cpufreq_update_policy on this device.
 * Defer to a workqueue so the notifier only records the state and returns.
 */
static void cpufreq_screen_off_work(struct work_struct *work);
static DECLARE_DELAYED_WORK(screen_off_work, cpufreq_screen_off_work);

static void cpufreq_screen_off_work(struct work_struct *work)
{
	unsigned int cpu;

	get_online_cpus();
	for_each_online_cpu(cpu)
		cpufreq_update_policy(cpu);
	put_online_cpus();
}

static void cpufreq_update_policies(void)
{
	schedule_delayed_work(&screen_off_work, 0);
}

static int msm_cpufreq_screen_off_adjust(struct notifier_block *nb,
					 unsigned long val, void *data)
{
	struct cpufreq_policy *policy = data;
	unsigned int cap = READ_ONCE(screen_off_cap_khz);

	if (val != CPUFREQ_ADJUST || !READ_ONCE(screen_off_capped))
		return NOTIFY_OK;

	if (policy->max > cap) {
		pr_debug("policy %u: capping max %u -> %u kHz (screen off)\n",
			policy->cpu, policy->max, cap);
		cpufreq_verify_within_limits(policy, policy->min, cap);
	}

	return NOTIFY_OK;
}

static struct notifier_block msm_cpufreq_adjust_notifier = {
	.notifier_call = msm_cpufreq_screen_off_adjust,
};

static int msm_cpufreq_fb_event(struct notifier_block *nb, unsigned long val,
				void *data)
{
	struct fb_event *event = data;
	bool capped;

	if (val != FB_EVENT_BLANK || !event->data)
		return NOTIFY_OK;

	capped = *(int *)event->data != FB_BLANK_UNBLANK;
	if (capped == READ_ONCE(screen_off_capped))
		return NOTIFY_OK;

	pr_info("screen %s: CPU ceiling %s\n",
		capped ? "off" : "on",
		capped ? "applied" : "released");
	WRITE_ONCE(screen_off_capped, capped);
	cpufreq_update_policies();

	return NOTIFY_OK;
}

static struct notifier_block msm_cpufreq_fb_notifier = {
	.notifier_call = msm_cpufreq_fb_event,
};

static ssize_t screen_off_cap_show(struct cpufreq_policy *policy,
				   char *buf)
{
	return sprintf(buf, "%u\n", screen_off_cap_khz);
}

static ssize_t screen_off_cap_store(struct cpufreq_policy *policy,
				    const char *buf, size_t count)
{
	unsigned int khz;
	int ret;

	ret = kstrtouint(buf, 0, &khz);
	if (ret)
		return ret;
	if (!khz)
		return -EINVAL;

	WRITE_ONCE(screen_off_cap_khz, khz);
	if (READ_ONCE(screen_off_capped))
		cpufreq_update_policies();

	return count;
}

static struct freq_attr screen_off_cap_attr =
	__ATTR(screen_off_cap_khz, 0644, screen_off_cap_show,
	       screen_off_cap_store);


static void msm_cpufreq_screen_off_init(void)
{
	cpufreq_register_notifier(&msm_cpufreq_adjust_notifier,
				 CPUFREQ_POLICY_NOTIFIER);
	fb_register_client(&msm_cpufreq_fb_notifier);
}

static struct freq_attr *msm_policy_attr[] = {
	&cpufreq_freq_attr_scaling_available_freqs,
#ifdef CONFIG_MSM8953_CPU_VOLTAGE_CONTROL
	&msm8953_uv_mv_table,
#endif
	&screen_off_cap_attr,
	NULL,
};

static void msm_cpufreq_ready(struct cpufreq_policy *policy)
{
	struct device_node *np;
	unsigned int cpu = policy->cpu;

	if (cdev[cpu])
		return;

	np = of_cpu_device_node_get(cpu);
	if (WARN_ON(!np))
		return;

	/*
	 * For now, just loading the cooling device;
	 * thermal DT code takes care of matching them.
	 */
	if (of_find_property(np, "#cooling-cells", NULL)) {
		cdev[cpu] = cpufreq_platform_cooling_register(policy, NULL);
		if (IS_ERR(cdev[cpu])) {
			pr_err("running cpufreq for CPU%d without cooling dev: %ld\n",
			       cpu, PTR_ERR(cdev[cpu]));
			cdev[cpu] = NULL;
		}
	}
	of_node_put(np);
}

static struct cpufreq_driver msm_cpufreq_driver = {
	/* lps calculations are handled here. */
	.flags		= CPUFREQ_STICKY | CPUFREQ_CONST_LOOPS |
				CPUFREQ_NEED_INITIAL_FREQ_CHECK,
	.init		= msm_cpufreq_init,
	.verify		= msm_cpufreq_verify,
	.target		= msm_cpufreq_target,
	.resolve_freq	= msm_cpufreq_resolve_freq,
	.get		= msm_cpufreq_get_freq,
	.name		= "msm",
	.attr		= msm_policy_attr,
	.ready		= msm_cpufreq_ready,
};

static struct cpufreq_frequency_table *cpufreq_parse_dt(struct device *dev,
						char *tbl_name, int cpu)
{
	int ret, nf, i, j;
	u32 *data;
	struct cpufreq_frequency_table *ftbl;

	/* Parse list of usable CPU frequencies. */
	if (!of_find_property(dev->of_node, tbl_name, &nf))
		return ERR_PTR(-EINVAL);
	nf /= sizeof(*data);

	if (nf == 0)
		return ERR_PTR(-EINVAL);

	data = devm_kzalloc(dev, nf * sizeof(*data), GFP_KERNEL);
	if (!data)
		return ERR_PTR(-ENOMEM);

	ret = of_property_read_u32_array(dev->of_node, tbl_name, data, nf);
	if (ret)
		return ERR_PTR(ret);

	ftbl = devm_kzalloc(dev, (nf + 1) * sizeof(*ftbl), GFP_KERNEL);
	if (!ftbl)
		return ERR_PTR(-ENOMEM);

	j = 0;
	for (i = 0; i < nf; i++) {
		unsigned long f;

		f = clk_round_rate(cpu_clk[cpu], data[i] * 1000);
		if (IS_ERR_VALUE(f))
			break;
		f /= 1000;

		/*
		 * Don't repeat frequencies if they round up to the same clock
		 * frequency.
		 *
		 */
		if (j > 0 && f <= ftbl[j - 1].frequency)
			continue;

		ftbl[j].driver_data = j;
		ftbl[j].frequency = f;
		j++;
	}

	ftbl[j].driver_data = j;
	ftbl[j].frequency = CPUFREQ_TABLE_END;

	devm_kfree(dev, data);

	return ftbl;
}

static int msm_cpufreq_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	char clk_name[] = "cpu??_clk";
	char tbl_name[] = "qcom,cpufreq-table-??";
	struct clk *c;
	int cpu, ret;
	struct cpufreq_frequency_table *ftbl;

	l2_clk = devm_clk_get(dev, "l2_clk");
	if (IS_ERR(l2_clk))
		l2_clk = NULL;

	for_each_possible_cpu(cpu) {
		snprintf(clk_name, sizeof(clk_name), "cpu%d_clk", cpu);
		c = devm_clk_get(dev, clk_name);
		if (cpu == 0 && IS_ERR(c))
			return PTR_ERR(c);
		else if (IS_ERR(c))
			c = cpu_clk[cpu-1];
		cpu_clk[cpu] = c;
	}
	hotplug_ready = true;

	/* Use per-policy governor tunable for some targets */
	if (of_property_read_bool(dev->of_node, "qcom,governor-per-policy"))
		msm_cpufreq_driver.flags |= CPUFREQ_HAVE_GOVERNOR_PER_POLICY;

	/* Parse commong cpufreq table for all CPUs */
	ftbl = cpufreq_parse_dt(dev, "qcom,cpufreq-table", 0);
	if (!IS_ERR(ftbl)) {
		for_each_possible_cpu(cpu)
			per_cpu(freq_table, cpu) = ftbl;
		goto out_register;
	}

	/*
	 * No common table. Parse individual tables for each unique
	 * CPU clock.
	 */
	for_each_possible_cpu(cpu) {
		snprintf(tbl_name, sizeof(tbl_name),
			 "qcom,cpufreq-table-%d", cpu);
		ftbl = cpufreq_parse_dt(dev, tbl_name, cpu);

		/* CPU0 must contain freq table */
		if (cpu == 0 && IS_ERR(ftbl)) {
			dev_err(dev, "Failed to parse CPU0's freq table\n");
			return PTR_ERR(ftbl);
		}
		if (cpu == 0) {
			per_cpu(freq_table, cpu) = ftbl;
			continue;
		}

		if (cpu_clk[cpu] != cpu_clk[cpu - 1] && IS_ERR(ftbl)) {
			dev_err(dev, "Failed to parse CPU%d's freq table\n",
				cpu);
			return PTR_ERR(ftbl);
		}

		/* Use previous CPU's table if it shares same clock */
		if (cpu_clk[cpu] == cpu_clk[cpu - 1]) {
			if (!IS_ERR(ftbl)) {
				dev_warn(dev, "Conflicting tables for CPU%d\n",
					 cpu);
				devm_kfree(dev, ftbl);
			}
			ftbl = per_cpu(freq_table, cpu - 1);
		}
		per_cpu(freq_table, cpu) = ftbl;
	}

out_register:
	ret = register_pm_notifier(&msm_cpufreq_pm_notifier);
	if (ret)
		return ret;

	ret = cpufreq_register_driver(&msm_cpufreq_driver);
	if (ret) {
		unregister_pm_notifier(&msm_cpufreq_pm_notifier);
		return ret;
	}

	msm_cpufreq_screen_off_init();

	return 0;
}

static const struct of_device_id msm_cpufreq_match_table[] = {
	{ .compatible = "qcom,msm-cpufreq" },
	{}
};

static struct platform_driver msm_cpufreq_plat_driver = {
	.probe = msm_cpufreq_probe,
	.driver = {
		.name = "msm-cpufreq",
		.of_match_table = msm_cpufreq_match_table,
	},
};

static int __init msm_cpufreq_register(void)
{
	int cpu, rc;

	for_each_possible_cpu(cpu) {
		mutex_init(&(per_cpu(suspend_data, cpu).suspend_mutex));
		per_cpu(suspend_data, cpu).device_suspended = 0;
		per_cpu(cached_resolve_freq, cpu) = UINT_MAX;
	}

	rc = platform_driver_register(&msm_cpufreq_plat_driver);
	if (rc < 0) {
		/* Unblock hotplug if msm-cpufreq probe fails */
		cpuhp_remove_state_nocalls(CPUHP_QCOM_CPUFREQ_PREPARE);
		cpuhp_remove_state_nocalls(CPUHP_AP_QCOM_CPUFREQ_STARTING);
		for_each_possible_cpu(cpu)
			mutex_destroy(&(per_cpu(suspend_data, cpu).
					suspend_mutex));
		return rc;
	}

	return 0;
}

subsys_initcall(msm_cpufreq_register);

static int __init msm_cpufreq_early_register(void)
{
	int ret;

	ret = cpuhp_setup_state_nocalls(CPUHP_AP_QCOM_CPUFREQ_STARTING,
					"AP_QCOM_CPUFREQ_STARTING",
					qcom_cpufreq_starting_cpu,
					qcom_cpufreq_dying_cpu);
	if (ret)
		return ret;

	ret = cpuhp_setup_state_nocalls(CPUHP_QCOM_CPUFREQ_PREPARE,
					"QCOM_CPUFREQ_PREPARE",
					qcom_cpufreq_up_cpu,
					qcom_cpufreq_dead_cpu);
	if (!ret)
		return ret;
	cpuhp_remove_state_nocalls(CPUHP_AP_QCOM_CPUFREQ_STARTING);
	return ret;
}
core_initcall(msm_cpufreq_early_register);
