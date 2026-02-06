# Polar Recorder (Home Assistant Integration)

Polar Recorder builds a **polar diagram** for your sailing boat by **recording boat speed (BSP)** into bins of **True Wind Angle (TWA)** and **True Wind Speed (TWS)**.
Over time, the matrix becomes a practical polar diagram you can use for sail trim, performance monitoring, and routing/tactics.

> Domain: `polar_recorder`

---

## What it does

- Listens to your existing HA sensor entities for:
  - **TWA** (True Wind Angle, degrees)
  - **TWS** (True Wind Speed, knots)
  - **BSP** (Boat Speed, knots)
- Bins the incoming measurements into a **TWA × TWS grid** (“polar matrix”)
- Stores the **best/representative BSP** observed for each bin (depending on your settings), updating as you sail around
- Provides:
  - A **matrix sensor** (state + attributes) that contains the recorded polar data
  - **Services** to start/stop recording and to manage/edit/export/import the matrix
  - **Helper number entities** for quick manual edits (set-cell workflow)

---

## Requirements

1. Home Assistant running (Core / Supervised / OS).
2. You already have entities providing:
   - TWA (°), e.g. from your NMEA stack
   - TWS (kn)
   - BSP (kn)
3. Reasonably stable, filtered inputs are recommended (especially TWS).

---

## Installation

### Manual installation (custom component)

1. Copy the integration folder into:

```
/config/custom_components/polar_recorder/
```

2. Ensure the component includes (at minimum):

```
__init__.py
manifest.json
const.py
coordinator.py
sensor.py
number.py
services.yaml
```

3. Restart Home Assistant.

4. Add the integration:
   - **Settings → Devices & services → Add integration → “Polar Recorder”**

---

## Entities

### 1) Polar Matrix sensor

The integration exposes a “matrix” sensor that represents the recorded polar data.

Typical attributes you will see (exact names can vary by version):

- `recording`: whether recording is enabled
- `matrix`: the stored polar matrix (can be large)
- configuration attributes such as:
  - `twa_min`, `twa_max`, `twa_step`
  - `tws_min`, `tws_max`, `tws_step`
  - fold/interpolate settings

**Tip:** The `matrix` attribute can be large. Avoid displaying it directly in dashboards; use export/import or custom cards/templating to visualize.

---

### 2) Helper Number entities (for editing)

Polar Recorder provides UI number entities that support manual edits:

- **Polar Edit TWA** (°) – choose the angle bin you want to edit
- **Polar Edit TWS** (kn) – choose the wind speed bin you want to edit
- **Polar Edit BSP** (kn) – the value you want to store
- **Polar Scale Factor** – multiplier used by the scale service

These are designed to work with the `set_cell` / `clear_cell` / `scale_line` services.

---

## Recording controls

Recording can be started/stopped at any time:

- When recording is **off**, the matrix is unchanged.
- When recording is **on**, the integration continuously processes incoming TWA/TWS/BSP and updates bins.

Services:
- `polar_recorder.start_recording`
- `polar_recorder.stop_recording`
- `polar_recorder.toggle_recording`

---

## Matrix management services

The integration exposes services to manage the matrix:

### Export CSV

`polar_recorder.export_csv`

Exports the polar matrix to a CSV file under `/config` (commonly `/config/www/...` so you can download under `/local/...`).

Example:

```yaml
service: polar_recorder.export_csv
data:
  path: /config/www/polars.csv
```

### Import CSV

`polar_recorder.import_csv`

Imports a CSV matrix from disk (backs up the current matrix first).

Options:
- `merge`: keep the maximum of imported vs existing values per bin (instead of overwrite)
- `fill_missing`: fill empty bins by averaging neighbors (conservative)

Example:

```yaml
service: polar_recorder.import_csv
data:
  path: /config/www/polars.csv
  merge: true
  fill_missing: false
```

### Reset matrix

`polar_recorder.reset`

Clears the polar matrix.

```yaml
service: polar_recorder.reset
```

### Backups

Create and restore snapshots of the matrix:

- `polar_recorder.backup_matrix`
- `polar_recorder.restore_matrix`

Restore selector:

- `which: latest | previous | oldest`

Example:

```yaml
service: polar_recorder.restore_matrix
data:
  which: latest
```

---

## Manual edits (advanced)

These are useful when you want to correct a bin, seed a matrix, or tweak a line.

### Set one cell (bin)

`polar_recorder.set_cell`

Sets/overrides one bin value (BSP) at given TWA/TWS.

```yaml
service: polar_recorder.set_cell
data:
  twa: 52.5
  tws: 12.0
  bsp: 7.1
```

### Clear one cell (bin)

`polar_recorder.clear_cell`

Deletes the value at the given TWA/TWS bin.

```yaml
service: polar_recorder.clear_cell
data:
  twa: 52.5
  tws: 12.0
```

### Scale an entire TWS line

`polar_recorder.scale_line`

Multiplies all bins at a specific TWS by a factor (e.g. 0.95 reduces the whole line by 5%).

```yaml
service: polar_recorder.scale_line
data:
  tws: 12
  factor: 0.95
```

---

## Recommended workflow

1. **Start recording** when you’re sailing in “normal” conditions (good wind, trimmed sails).
2. Let it collect for multiple sessions:
   - Upwind, reach, downwind
   - Different wind strengths
3. **Backup** periodically.
4. Use **export CSV** to visualize in external tools or scripts.
5. Use **import CSV** (merge/fill) to combine voyages or refine gaps.
6. Apply **scale_line** if you discover systematic bias (e.g., calibration offset).

---

## Tips for better polars

- Stop recording as soon as you start the engine.
- Use a minimum TWS threshold to avoid “calm noise”.
- Avoid recording while surfing down waves.
- Let the TWS EMA/smoothing settle before trusting a bin.
- Record on both tacks (especially if sensors are imperfect).
- Prefer “steady-state” trimmed runs.

---

## Troubleshooting

### Matrix stays empty
- Ensure your TWA/TWS/BSP entities have valid numeric states.
- Start recording (`polar_recorder.start_recording`).
- Verify values are above any minimum thresholds (min TWS / min BSP).

### Values look too low/high
- Confirm units:
  - TWA in degrees
  - TWS/BSP in knots
- Consider applying smoothing or ignoring calms.
- If you imported data, check CSV headers/format used by the exporter.

### CSV not downloadable
- Export to `/config/www/...`
- Access via `/local/...` in your browser.

---

## Service reference

This integration exposes the following services:

- `polar_recorder.export_csv`
- `polar_recorder.import_csv`
- `polar_recorder.reset`
- `polar_recorder.start_recording`
- `polar_recorder.stop_recording`
- `polar_recorder.toggle_recording`
- `polar_recorder.backup_matrix`
- `polar_recorder.restore_matrix`
- `polar_recorder.set_cell`
- `polar_recorder.clear_cell`
- `polar_recorder.scale_line`

(See **Services** UI in Home Assistant for the exact field selectors and defaults.)

---

## Changelog

Keep a short changelog here if you publish releases (HACS/GitHub).
