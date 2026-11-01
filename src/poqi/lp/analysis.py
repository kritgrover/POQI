"""Small analytical checks for the fixed-coefficient memory LP."""


def service_memory_lower_bound(result, mean_residence_time, *, distillation_pairs=1):
    """Node lower bounds from final service alone, excluding all preparation."""
    from collections.abc import Mapping

    bounds = dict.fromkeys(result.node_occupancy, 0.0)
    for pair, completion in result.completion_rates.items():
        if isinstance(mean_residence_time, Mapping):
            tau = mean_residence_time.get(pair, mean_residence_time.get(tuple(reversed(pair))))
            if tau is None:
                raise ValueError(f"Missing mean_residence_time for {pair!r}")
        else:
            tau = mean_residence_time
        for node in pair:
            bounds[node] += distillation_pairs * tau * completion
    return bounds


def proportional_service_ratio(completion_rates, demand_rate):
    """Minimum positive-demand completion ratio, or None for an empty workload."""
    ratios = []
    for pair, demand in demand_rate.items():
        if demand > 0:
            completed = completion_rates.get(pair, completion_rates.get(tuple(reversed(pair)), 0.0))
            ratios.append(completed / demand)
    return min(ratios) if ratios else None
