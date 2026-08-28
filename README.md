# Muon Detector

Two scripts for logging cosmic ray muon pulses off a Rigol DS1000Z-series
oscilloscope over USB (via PyVISA), using a PIN diode array as the
detector rather than a traditional photomultiplier tube.

- `muon_event_logger.py` — single-channel logger. Arms the scope on a
  falling edge trigger, waits for a pulse, measures amplitude and
  duration, and logs each event to CSV with a screenshot.
- `muon_coincidence_logger.py` — two-channel version. Captures both
  channels on the same trigger and flags a coincidence when both channels
  show a pulse within a configurable time window, sorting screenshots into
  `coincidences/` and `singles/` accordingly.

## Detector note

This was built around a **PIN diode array**, not a scintillator +
photomultiplier tube. PIN diodes are far less sensitive and have a much
slower response than a PMT, so don't expect clean, sharp PMT-style pulses
in the screenshots below — the traces are rounded and noisy, and plenty of
triggers are borderline noise rather than a clean particle hit. This is
expected behavior for this detector, not a bug in the capture.

## Example captures

![Untriggered rounded pulse](screenshots/pulse_000005.png)
![Triggered dip pulse](screenshots/pulse_000100.png)

Both from the same run. Note the slow, rounded rise/fall — this is the PIN
diode's own response shape, not particle physics.

## Requirements

- `pip install pyvisa numpy`
- Rigol scope connected via USB, with the VISA address updated at the top
  of each script (`VISA_ADDRESS`) to match your device. Find yours with:
  ```python
  import pyvisa
  print(pyvisa.ResourceManager().list_resources())
  ```

## Usage

```
python muon_event_logger.py
```
or
```
python muon_coincidence_logger.py
```

Both scripts arm immediately and print each captured event as it happens.
Type `exit` and press Enter to stop cleanly — this lets the CSV buffer
flush and the run finish gracefully instead of killing the process
mid-write.

Output goes to a timestamped folder on `D:\`, e.g.
`D:\Muon Detector 2026-01-31 01-56-35\`, containing a CSV of events and a
`screenshots` folder of the scope display at each trigger. Change the
`base_folder` line near the top of each script if you don't have (or don't
want output on) a `D:` drive.

## How it works

- Both scripts arm the scope with `:SINGLE` and poll `:TRIG:STAT?` until
  it reports `STOP`, meaning a trigger fired and a waveform is captured.
- `DEAD_TIME_S` discards any trigger that fires too soon after the last
  accepted one, to avoid double-counting ringing/bounce as multiple pulses.
- Pulse amplitude comes from raw waveform data pulled with
  `:WAV:DATA?` and converted from ADC counts to volts using the scope's
  own `:WAV:YINC?` / `:WAV:YREF?` / `:WAV:YOR?` scaling values.
- The screenshot is grabbed with `:DISP:DATA? ON,PNG` and saved after
  stripping the SCPI binary-block header that data comes wrapped in.
- The coincidence logger triggers only off channel 1, then reads both
  channels from that single acquisition and compares each channel's pulse
  center time; if they fall within `COINCIDENCE_WINDOW_S` of each other,
  it's logged as a coincidence rather than two independent singles.

## Notes and limitations

- **Screenshots are actually BMP files saved with a `.png` extension.**
  The scope's `:DISP:DATA? ON,PNG` response isn't being converted to real
  PNG by these scripts — what's saved is raw BMP data. They'll open fine
  if you rename them to `.bmp`, but any tool expecting real PNG (including
  most image viewers, if opened by double-click relying on the extension)
  will fail to decode them as-is.
- `duration_s` in the CSV is unreliable and reads `0.0` for a large
  fraction of events. `find_pulse()`'s edge-detection loop only records a
  duration when it finds both a start and an end crossing within the
  capture window; if the pulse doesn't fall back below `HIGH_LEVEL_V`
  before the trace ends, duration silently reports `0.0` instead of
  flagging that the pulse was cut off.
- Both scripts poll `:TRIG:STAT?` every 2ms in a busy loop rather than
  using the scope's own event/interrupt mechanism, so CPU usage is higher
  than it needs to be while armed and waiting.
- `LOW_LEVEL_V` / `HIGH_LEVEL_V` / `TRIGGER_LEVEL_V` are tuned to this
  specific PIN diode setup's noise floor and gain. Swapping detectors (or
  even just changing the bias voltage) will likely need these re-tuned by
  hand, since there's no automatic baseline calibration.
- `COINCIDENCE_WINDOW_S` (500µs) is generous relative to actual muon
  transit time between two closely-stacked detectors — it was chosen to
  tolerate the PIN diode's slow rise time, not to reflect a real
  time-of-flight window.
