import pyvisa
import numpy as np
import time
import threading
from datetime import datetime
from pathlib import Path

VISA_ADDRESS = "USB0::0x1AB1::0x04CE::DS1ZA224211026::INSTR"
CH1 = 1
CH2 = 2

TRIGGER_LEVEL_V = -0.035
LOW_LEVEL_V = -0.045
HIGH_LEVEL_V = 0

TRIGGER_HOLDOFF_S = 0.5
DEAD_TIME_S = 0.5
COINCIDENCE_WINDOW_S = 500e-6

MIN_SAMPLES = 50

stop_requested = False

def exit_listener():
    global stop_requested
    while True:
        if input().strip().lower() == "exit":
            stop_requested = True
            print("\nExit requested.")
            break

threading.Thread(target=exit_listener, daemon=True).start()

run_start = datetime.now()
base_folder = Path("D:/") / f"Muon Detector {run_start.strftime('%Y-%m-%d %H-%M-%S')}"
coinc_folder  = base_folder / "screenshots" / "coincidences"
single_folder = base_folder / "screenshots" / "singles"
coinc_folder.mkdir(parents=True, exist_ok=True)
single_folder.mkdir(parents=True, exist_ok=True)

print(f"Saving screenshots to: {base_folder / 'screenshots'}")
print("Type 'exit' and press Enter to stop.\n")

rm = pyvisa.ResourceManager()
scope = rm.open_resource(VISA_ADDRESS)
scope.timeout = 30000

print(scope.query("*IDN?").strip())

scope.write(":STOP")
scope.write(f":CHAN{CH1}:COUP DC")
scope.write(f":CHAN{CH1}:DISP ON")
scope.write(f":CHAN{CH2}:COUP DC")
scope.write(f":CHAN{CH2}:DISP ON")

scope.write(":TRIG:MODE EDGE")
scope.write(f":TRIG:EDGE:SOUR CHAN{CH1}")
scope.write(":TRIG:EDGE:SLOP NEG")
scope.write(f":TRIG:EDGE:LEV {TRIGGER_LEVEL_V}")
scope.write(":TRIG:SWE NORM")
scope.write(f":TRIG:HOLD {TRIGGER_HOLDOFF_S}")

# Push trigger to 90% of screen for ~540us of pre-trigger buffer
scope.write(":TIM:SCAL 50e-6")
scope.write(f":TIM:OFFS {(90/100 - 0.5) * 50e-6 * 12}")

scope.write(":WAV:MODE RAW")
scope.write(":WAV:FORM BYTE")
scope.write(":ACQ:MDEP 12000")

last_event_time = None
last_physical_event = 0.0
event_id = 0
coinc_count = 0
single_count = 0

print("Armed. Waiting for pulses...\n")

def find_pulse(volts, xinc):
    state = "idle"
    start_idx = end_idx = None
    for i, v in enumerate(volts):
        if state == "idle" and v < LOW_LEVEL_V:
            state = "active"
            start_idx = i
        elif state == "active" and v > HIGH_LEVEL_V:
            end_idx = i
            break
    if start_idx is None:
        return None
    if end_idx is None:
        end_idx = len(volts) - 1
    centre   = (start_idx + end_idx) / 2 * xinc
    duration = (end_idx - start_idx) * xinc
    return centre, duration

try:
    while not stop_requested:
        scope.write(":SINGLE")

        while not stop_requested:
            if scope.query(":TRIG:STAT?").strip() == "STOP":
                break
            time.sleep(0.002)

        if stop_requested:
            break

        now = time.perf_counter()
        if now - last_physical_event < DEAD_TIME_S:
            continue

        # Read CH1
        scope.write(f":WAV:SOUR CHAN{CH1}")
        raw1  = np.array(scope.query_binary_values(":WAV:DATA?", datatype="B"))
        if raw1.size < MIN_SAMPLES:
            continue
        yinc  = float(scope.query(":WAV:YINC?"))
        yref  = float(scope.query(":WAV:YREF?"))
        yorig = float(scope.query(":WAV:YOR?"))
        xinc  = float(scope.query(":WAV:XINC?"))
        ch1_v = (raw1 - yref) * yinc + yorig

        # Read CH2 (same acquisition)
        scope.write(f":WAV:SOUR CHAN{CH2}")
        raw2   = np.array(scope.query_binary_values(":WAV:DATA?", datatype="B"))
        yinc2  = float(scope.query(":WAV:YINC?"))
        yref2  = float(scope.query(":WAV:YREF?"))
        yorig2 = float(scope.query(":WAV:YOR?"))
        ch2_v  = (raw2 - yref2) * yinc2 + yorig2

        # Analyse
        ch1_vpp   = float(np.max(ch1_v) - np.min(ch1_v))
        ch2_vpp   = float(np.max(ch2_v) - np.min(ch2_v))
        ch1_pulse = find_pulse(ch1_v, xinc)
        ch2_pulse = find_pulse(ch2_v, xinc)
        ch1_duration = ch1_pulse[1] if ch1_pulse else 0.0
        ch2_duration = ch2_pulse[1] if ch2_pulse else 0.0

        # Coincidence decision
        is_coincidence = False
        delta_t = None
        if ch1_pulse and ch2_pulse:
            delta_t = ch2_pulse[0] - ch1_pulse[0]
            if abs(delta_t) <= COINCIDENCE_WINDOW_S:
                is_coincidence = True

        # Rate
        rate = 0.0 if last_event_time is None else 1.0 / (now - last_event_time)
        last_event_time     = now
        last_physical_event = now

        # Screenshot
        scope.write(":STOP")
        scope.write(":DISP:DATA? ON,PNG")
        png = scope.read_raw()
        if png[0:1] == b"#":
            header_len = int(png[1:2])
            data_len   = int(png[2:2+header_len])
            png        = png[2+header_len:2+header_len+data_len]

        if is_coincidence:
            coinc_count += 1
            img_name = f"coinc_{event_id:06d}.png"
            with open(coinc_folder / img_name, "wb") as f:
                f.write(png)
            print(f"*** COINC {coinc_count:04d} | event {event_id} | CH1 Vpp={ch1_vpp:.3f}V dur={ch1_duration:.2e}s | CH2 Vpp={ch2_vpp:.3f}V dur={ch2_duration:.2e}s | Δt={delta_t*1e6:.2f}µs | rate={rate:.2f}Hz")
        else:
            single_count += 1
            img_name = f"single_{event_id:06d}.png"
            with open(single_folder / img_name, "wb") as f:
                f.write(png)
            ch2_note = f"pulse outside window (Δt={delta_t*1e6:.2f}µs)" if delta_t is not None else "no pulse"
            print(f"    single {single_count:04d} | event {event_id} | CH1 Vpp={ch1_vpp:.3f}V | CH2 {ch2_note} | rate={rate:.2f}Hz")

        event_id += 1

except Exception as e:
    print("ERROR:", e)

print(f"\nDone. {event_id} total events: {coinc_count} coincidences, {single_count} singles.")
print(f"Screenshots saved to: {base_folder / 'screenshots'}")
