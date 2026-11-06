# Data

`Day-ahead_prices_202610240600_202611040600_Quarterhour.csv`

- **Source:** Bundesnetzagentur | SMARD.de (www.smard.de), CC BY 4.0
- **Series used:** Germany/Luxembourg (DE-LU) day-ahead price, EUR/MWh
- **Resolution:** 15 minutes
- **Range:** 24 Oct 2026 06:00 to 4 Nov 2026 06:00, German local time (Europe/Berlin)
- **Downloaded:** [add date]
- **Format:** semicolon-separated, English export (dates like "Oct 24, 2026 6:00 AM", dot decimals)

**Daylight saving:** clocks went back on 25 Oct 2026, so the local times
2:00-2:45 AM appear twice (rows 82-89). Convert timestamps to UTC, or number
intervals sequentially, when loading. Only the DE-LU column is used; other
columns contain "-" for missing values.
