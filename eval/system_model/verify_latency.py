#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import benchmark_model as m
m.verify_standardized_system_model()
assert all(abs(x-500)<1e-9 for x in m.baseline_budget.values())
assert all(m.ref_latency[f] <= 500 for f in m.flows)
assert m.resource_feasible(m.p0,m.base)
print('Shortest-route baseline (ms):',m.ref_latency)
print('Budgets (ms):',m.baseline_budget)
