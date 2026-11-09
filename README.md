# vpp-dispatch-EU

How much does a virtual power plant (VPP) miss its schedule when commands to home batteries are lost, duplicated or delayed, or when devices go offline, and how much of that error do idempotent commands, retries with deadlines and state reconciliation remove?

## Layout

```
contracts/   message formats shared by all components (JSON Schema)
data/        German day-ahead price snapshot (see data/README.md)
simulation/  Python simulation package `vppsim`, its tests and experiments
```

## Run the tests

```bash
cd simulation
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .   # style and docstring rules
```

## Conventions

- Power in kW: positive = discharging (delivering to the grid), negative = charging.
- Energy and state of charge in kWh; simulation steps of 15 minutes.

## Command rule

Each device's commands carry a version that only increases. The VPP must:

- give every changed instruction a new, higher version, and
- re-send exactly the same command (same ID and version) when retrying.

The control unit applies only versions newer than the last one it applied. A repeat of that last command is acknowledged as `duplicate`, an older one as `stale`, and the same version with a different ID as `conflict` (a VPP bug).

## Commercial VPP: naive vs reliable dispatch

```bash
cd simulation
python -m vppsim.experiments.commercial_vpp
```

A commercial VPP trades on the energy market: here, a fleet that charges when day-ahead prices are lowest and discharges when they are highest. A commercial VPP can also sell balancing services to the transmission grid operator (TSO); this one does not yet. A technical VPP is different: it works for the local distribution grid operator (DSO), using the same devices to keep the local network within its limits. Each run is one day (96 steps of 15 minutes) with 100 batteries of three types. For each step there are three fleet totals: **planned** (the price-based plan), **allocated** (what the VPP asked for, within the batteries' limits) and **delivered** (what the batteries did). Planned minus allocated is what the batteries physically could not do; allocated minus delivered is the **tracking error**, caused by the network.

Two dispatchers are compared:

- **Naive:** sends a command when a setpoint changes and never checks that it arrived.
- **Reliable:** re-sends the identical command (same ID and version) until a reply confirms it. The first wait is 15 s (the IEC 60870-5-104 default for an unanswered frame) and doubles each time: tries at 0, 15, 45, 105, 225 and 465 s, within the 15-minute step. A reply of `duplicate` means an earlier copy had already arrived and only its reply was lost, so it confirms the command and counts as an unnecessary retry.

### First results (one day, 100 batteries, seed 1)

| Network | Dispatcher | Tracking error (RMSE) | Commands confirmed | Sends per command | Time to confirm, median / p95 | Unnecessary retries |
|---|---|---|---|---|---|---|
| Perfect | naive | 0.00 kW | 100% | 1.00 | 0 / 0 s | 0 |
| Perfect | reliable | 0.00 kW | 100% | 1.00 | 0 / 0 s | 0 |
| 10% loss each way | naive | 22.07 kW | 79.9% | 1.00 | — | — |
| 10% loss each way | reliable | 2.90 kW | 100% | 1.25 | 0 / 15 s | 141 |

Retries remove all of the error caused by lost commands: with loss on commands only, the reliable dispatcher's tracking error is exactly zero. The remaining 2.90 kW comes from lost battery reports: the VPP splits the target using an out-of-date state of charge, and asks some batteries for more than they can give. Both dispatchers show the same 2.90 kW with loss on reports only. Retries cannot fix this; state reconciliation (Phase 2) is meant to.

## Network and faults

Messages travel through a publish/subscribe broker modelled on MQTT, with one topic per device and direction (`vpp/der/{id}/cmd`, `/ack`, `/telemetry`). `InMemoryBroker` is a perfect broker; `FaultyBroker` adds message loss and duplication, set separately for commands (down) and replies (up).

Each message's fate is decided from its identity (seed, topic, message, fault type, attempt), not from a running random sequence. So both dispatchers face exactly the same faults on the same messages, and a retry gets its own independent chance. The in-memory broker is replaced by a real MQTT broker in Phase 3.

### How this maps to German practice

| Link | In Germany | In this project |
|---|---|---|
| TSO ↔ VPP (balancing) | Telecontrol link set by the TSO, in practice usually IEC 60870-5-104 | Not modelled; the VPP trades on day-ahead prices only |
| VPP ↔ site box | The VPP operator's own box over 4G mobile, with a proprietary protocol (for example the Next Kraftwerke Next Box) | MQTT-style broker, standing in for this link; this is where messages are lost or repeated |
| Site box ↔ battery | Modbus RTU, or analog/digital signals | A direct call from control unit to battery: local and reliable |
| Grid operator ↔ home device (§14a EnWG) | Smart meter gateway and FNN control box, IEC 61850 over the gateway's CLS channel; EEBus to wallboxes and heat pumps | Not modelled |
| Inside the VPP | No standard: each operator chooses its own queues, APIs and databases | In-process Python objects |

The 15 s retry wait matches the IEC 60870-5-104 default for an unanswered frame (`t1`).

## Roadmap

- **Phase 1 (in progress):** single-process simulation; naive vs reliable dispatcher under message loss (first results above); CI.
- **Phase 2:** full fault set (duplicates, delays, outages, stale telemetry), reconciler, command log, crash recovery; control units serving several devices, and correlated outages when devices share a control unit.
- **Phase 3:** VPP service in C#, real MQTT broker, PostgreSQL.
- **Phase 4:** failover between two VPP instances.

## Limitations

- Power is held constant within each 15-minute step, so a command confirmed after a retry counts as followed for the whole step; the seconds show up only in the time to confirm.
- Results so far are from one day and one seed.
- Batteries follow VPP setpoints only; household consumption and backup reserves are not modelled.
- The faulty broker models failure modes (loss, duplication, delay, outage), not real protocols.

## License

MIT. Price data: Bundesnetzagentur | SMARD.de, CC BY 4.0.
