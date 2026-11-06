# vpp-dispatch-EU

How much does a virtual power plant (VPP) miss its schedule when commands to
home batteries are lost, duplicated or delayed, or when devices go offline,
and how much of that error do idempotent commands, retries with deadlines and
state reconciliation remove?

**Status (5 Nov 2026):** device physics (DER base class, battery), the site
control unit (versioned command handling, telemetry) and the network (message
broker, perfect and faulty), with tests.
Dispatchers and experiments in progress.

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

The control unit applies only versions newer than the last one it applied.
A repeat of that last command is acknowledged as `duplicate`, an older one as
`stale`, and the same version with a different ID as `conflict` (a VPP bug).

## Network and faults

Messages travel through a publish/subscribe broker modelled on MQTT, with one topic
per device and direction (`vpp/der/{id}/cmd`, `/ack`, `/telemetry`).
`InMemoryBroker` is a perfect broker; `FaultyBroker` adds message loss and
duplication, set separately for commands (down) and replies (up).

Each message's fate is decided from its identity (seed, topic, message,
fault type, attempt), not from a running random sequence. So both
dispatchers face exactly the same faults on the same messages, and a retry
gets its own independent chance. The in-memory broker is replaced by a real
MQTT broker in Phase 3.

## Roadmap

- **Phase 1 (in progress):** single-process simulation; naive vs reliable
  dispatcher under message loss.
- **Phase 2:** full fault set (duplicates, delays, outages, stale telemetry),
  reconciler, command log, crash recovery; control units serving several
  devices, and correlated outages when devices share a control unit.
- **Phase 3:** VPP service in C#, real MQTT broker, PostgreSQL.
- **Phase 4:** failover between two VPP instances.

## Limitations

- Power is held constant within each 15-minute step.
- Batteries follow VPP setpoints only; household consumption and backup
  reserves are not modelled.
- The faulty broker models failure modes (loss, duplication, delay,
  outage), not real protocols.

## License

MIT. Price data: Bundesnetzagentur | SMARD.de, CC BY 4.0.
