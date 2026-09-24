"""Generate data/enact_scenario/{node,link}_state_timeseries.csv.

Not part of the runtime pipeline -- a one-off dataset-generation script, on the
same footing as scripts/generate_intent_dataset.py.

node_state_timeseries.csv covers all 6 nodes of data/enact_scenario/nodes.csv
over one coherent 3-day timeline (the real "pods_on" campaign window):
  - rpi4 / vm-node: real values resampled from dataset/enact/node_telemetry_pods_on.csv
    (source="real").
  - the 4 generic nodes (iot-gw1, edge-srv1, fog-node1, cloud-vm2): synthetic
    series (source="synthetic"), sampled per-tier around the mean/CV observed
    on the closest real analog (rpi4 for edge/iot, vm-node for fog/cloud --
    see dataset_analysis.ipynb 10.1), with one deliberate overload window
    injected on edge-srv1 to act as a reconfiguration trigger.

link_state_timeseries.csv covers all 8 links of data/enact_scenario/links.csv
on the same timeline:
  - L4 (rpi4<->vm-node): bandwidth_utilization_mbps derived from the real
    rx_bps/tx_bps of both endpoints (source="real"); latency/packet_loss
    jittered around the static links.csv baseline.
  - every other link: fully synthetic, jittered around its static baseline,
    with one deliberate degradation window injected on L5 (edge-srv1<->fog-node1)
    as a second, network-side reconfiguration trigger.
"""

from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(seed=42)
DATA_DIR = Path("dataset/enact")
OUT_DIR = Path("data/enact_scenario")
RESAMPLE_INTERVAL = "15min"

RENAME = {
    "CPU (%)": "cpu_pct",
    "MEM (%)": "mem_pct",
    "fs (%)": "fs_pct",
    "Energy (watts)": "energy_w",
    "rx (B/sec)": "rx_bps",
    "tx (B/sec)": "tx_bps",
}


def load_real_node_series() -> pd.DataFrame:
    """Resample the real pods_on campaign to one row per node per RESAMPLE_INTERVAL."""
    df = pd.read_csv(DATA_DIR / "node_telemetry_pods_on.csv").rename(columns=RENAME)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    resampled = (
        df.set_index("timestamp")
        .groupby("node_name")[["cpu_pct", "mem_pct", "fs_pct", "energy_w", "rx_bps", "tx_bps"]]
        .resample(RESAMPLE_INTERVAL)
        .mean()
        .dropna()
        .reset_index()
        .rename(columns={"node_name": "node_id"})
    )
    resampled["source"] = "real"
    return resampled


# Per-tier synthetic calibration: (mean, std) per metric, loosely derived from
# the real rpi4 (edge/iot analog) and vm-node (fog/cloud analog) descriptive
# stats computed in dataset_analysis.ipynb section 10 (pods_on condition).
TIER_PROFILE = {
    "iot-gw1": dict(cpu_pct=(0.15, 0.06), mem_pct=(0.55, 0.05), fs_pct=(0.40, 0.02),
                    energy_w=(4.5, 0.6), rx_bps=(8_000, 3_000), tx_bps=(9_000, 3_500)),
    "edge-srv1": dict(cpu_pct=(0.20, 0.08), mem_pct=(0.60, 0.06), fs_pct=(0.55, 0.03),
                       energy_w=(45.0, 5.0), rx_bps=(60_000, 20_000), tx_bps=(70_000, 22_000)),
    "fog-node1": dict(cpu_pct=(0.25, 0.05), mem_pct=(0.50, 0.03), fs_pct=(0.60, 0.02),
                       energy_w=(80.0, 6.0), rx_bps=(400_000, 80_000), tx_bps=(500_000, 90_000)),
    "cloud-vm2": dict(cpu_pct=(0.20, 0.04), mem_pct=(0.52, 0.02), fs_pct=(0.70, 0.01),
                       energy_w=(85.0, 5.0), rx_bps=(650_000, 100_000), tx_bps=(850_000, 120_000)),
}

# Deliberate overload trigger: edge-srv1 saturates for a contiguous stretch
# near the middle of the timeline (fraction-of-length window).
OVERLOAD_NODE = "edge-srv1"
OVERLOAD_WINDOW = (0.45, 0.55)
OVERLOAD_CPU = (0.92, 0.03)
OVERLOAD_MEM = (0.88, 0.03)
OVERLOAD_ENERGY = (78.0, 4.0)


def clip01(x: np.ndarray) -> np.ndarray:
    return np.clip(x, 0.0, 1.0)


def synth_node_series(node_id: str, timestamps: pd.DatetimeIndex) -> pd.DataFrame:
    n = len(timestamps)
    profile = TIER_PROFILE[node_id]
    rows = {"timestamp": timestamps, "node_id": node_id}
    for metric, (mean, std) in profile.items():
        rows[metric] = RNG.normal(mean, std, n)

    if node_id == OVERLOAD_NODE:
        lo = int(n * OVERLOAD_WINDOW[0])
        hi = int(n * OVERLOAD_WINDOW[1])
        rows["cpu_pct"][lo:hi] = RNG.normal(*OVERLOAD_CPU, hi - lo)
        rows["mem_pct"][lo:hi] = RNG.normal(*OVERLOAD_MEM, hi - lo)
        rows["energy_w"][lo:hi] = RNG.normal(*OVERLOAD_ENERGY, hi - lo)

    for pct_col in ("cpu_pct", "mem_pct", "fs_pct"):
        rows[pct_col] = clip01(rows[pct_col])
    for positive_col in ("energy_w", "rx_bps", "tx_bps"):
        rows[positive_col] = np.clip(rows[positive_col], 0, None)

    df = pd.DataFrame(rows)
    df["source"] = "synthetic"
    return df


def build_node_state_timeseries() -> pd.DataFrame:
    real = load_real_node_series()
    timestamps = pd.DatetimeIndex(sorted(real["timestamp"].unique()))

    synthetic = pd.concat(
        [synth_node_series(node_id, timestamps) for node_id in TIER_PROFILE], ignore_index=True
    )

    cols = ["node_id", "timestamp", "cpu_pct", "mem_pct", "fs_pct", "energy_w", "rx_bps", "tx_bps", "source"]
    combined = pd.concat([real[cols], synthetic[cols]], ignore_index=True)
    return combined.sort_values(["node_id", "timestamp"]).reset_index(drop=True)


# Static baselines copied from data/enact_scenario/links.csv (kept in sync by hand --
# this script only adds dynamics around them, it does not read links.csv back in).
LINK_BASELINE = {
    "L1": dict(bandwidth_mbps=100, latency_ms=10, packet_loss_rate=0.02),
    "L2": dict(bandwidth_mbps=100, latency_ms=12, packet_loss_rate=0.02),
    "L3": dict(bandwidth_mbps=500, latency_ms=6, packet_loss_rate=0.01),
    "L4": dict(bandwidth_mbps=8000, latency_ms=22, packet_loss_rate=0.005),
    "L5": dict(bandwidth_mbps=1000, latency_ms=4, packet_loss_rate=0.003),
    "L6": dict(bandwidth_mbps=9000, latency_ms=24, packet_loss_rate=0.002),
    "L7": dict(bandwidth_mbps=9000, latency_ms=24, packet_loss_rate=0.002),
    "L8": dict(bandwidth_mbps=10000, latency_ms=2, packet_loss_rate=0.001),
}

# Deliberate degradation trigger: L5 (edge-srv1<->fog-node1) degrades for a
# contiguous stretch -- a second, network-side reconfiguration trigger,
# independent of the compute-side one injected on edge-srv1 above.
DEGRADED_LINK = "L5"
DEGRADED_WINDOW = (0.60, 0.68)
DEGRADED_LATENCY = (45.0, 8.0)
DEGRADED_LOSS = (0.08, 0.02)


def build_link_state_timeseries(node_ts: pd.DataFrame) -> pd.DataFrame:
    timestamps = pd.DatetimeIndex(sorted(node_ts["timestamp"].unique()))
    n = len(timestamps)

    rpi4 = node_ts[node_ts["node_id"] == "rpi4"].set_index("timestamp")
    vm = node_ts[node_ts["node_id"] == "vm-node"].set_index("timestamp")

    rows = []
    for link_id, baseline in LINK_BASELINE.items():
        if link_id == "L4":
            # Real-derived: bandwidth utilization proxy from both endpoints' rx+tx (bytes/s -> Mbps).
            util_bps = (rpi4["rx_bps"] + rpi4["tx_bps"] + vm["rx_bps"] + vm["tx_bps"]).reindex(timestamps)
            bandwidth_util_mbps = (util_bps * 8 / 1_000_000).to_numpy()
            latency_ms = RNG.normal(baseline["latency_ms"], 1.5, n)
            packet_loss_rate = np.clip(RNG.normal(baseline["packet_loss_rate"], 0.001, n), 0, None)
            source = np.full(n, "real-derived")
        else:
            bandwidth_util_mbps = np.clip(
                RNG.normal(baseline["bandwidth_mbps"] * 0.3, baseline["bandwidth_mbps"] * 0.08, n), 0, None
            )
            latency_ms = np.clip(RNG.normal(baseline["latency_ms"], baseline["latency_ms"] * 0.15, n), 0, None)
            packet_loss_rate = np.clip(
                RNG.normal(baseline["packet_loss_rate"], baseline["packet_loss_rate"] * 0.3, n), 0, None
            )
            source = np.full(n, "synthetic")

        if link_id == DEGRADED_LINK:
            lo = int(n * DEGRADED_WINDOW[0])
            hi = int(n * DEGRADED_WINDOW[1])
            latency_ms[lo:hi] = np.clip(RNG.normal(*DEGRADED_LATENCY, hi - lo), 0, None)
            packet_loss_rate[lo:hi] = np.clip(RNG.normal(*DEGRADED_LOSS, hi - lo), 0, None)

        rows.append(pd.DataFrame({
            "link_id": link_id,
            "timestamp": timestamps,
            "bandwidth_utilization_mbps": bandwidth_util_mbps,
            "latency_ms": latency_ms,
            "packet_loss_rate": packet_loss_rate,
            "source": source,
        }))

    return pd.concat(rows, ignore_index=True).sort_values(["link_id", "timestamp"]).reset_index(drop=True)


def main() -> None:
    node_ts = build_node_state_timeseries()
    node_ts.to_csv(OUT_DIR / "node_state_timeseries.csv", index=False)
    print(f"wrote {len(node_ts)} rows to {OUT_DIR / 'node_state_timeseries.csv'}")

    link_ts = build_link_state_timeseries(node_ts)
    link_ts.to_csv(OUT_DIR / "link_state_timeseries.csv", index=False)
    print(f"wrote {len(link_ts)} rows to {OUT_DIR / 'link_state_timeseries.csv'}")


if __name__ == "__main__":
    main()
