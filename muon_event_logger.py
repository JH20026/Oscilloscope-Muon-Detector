import pyvisa
import numpy as np
import csv
import time
import threading
from datetime import datetime
from pathlib import Path

VISA_ADDRESS = "USB0::0x1AB1::0x04CE::DS1ZA224211026::INSTR"
CHANNEL = 1

TRIGGER_LEVEL_V = -0.035
LOW_LEVEL_V = -0.045
HIGH_LEVEL_V = 0

TRIGGER_HOLDOFF_S = 0.5
DEAD_TIME_S = 0.5

MIN_SAMPLES = 50
FLUSH_EVERY_N_EVENTS = 10

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
base_folder.mkdir(parents=True, exist_ok=True)

csv_file = base_folder / "pulse_events.csv"
img_folder = base_folder / "screenshots"
img_folder.mkdir(exist_ok=True)

print(f"Saving data to: {base_folder}")
print("Type 'exit' and press Enter to stop.\n")

rm = pyvisa.ResourceManager()
scope = rm.open_resource(VISA_ADDRESS)
scope.timeout = 30000

print(scope.query("*IDN?").strip())

scope.write(":STOP")
scope.write(f":CHAN{CHANNEL}:COUP DC")
scope.write(f":CHAN{CHANNEL}:DISP ON")

scope.write(":TRIG:MODE EDGE")
scope.write(f":TRIG:EDGE:SOUR CHAN{CHANNEL}")
scope.write(":TRIG:EDGE:SLOP NEG")
scope.write(f":TRIG:EDGE:LEV {TRIGGER_LEVEL_V}")
scope.write(":TRIG:SWE NORM")
scope.write(f":TRIG:HOLD {TRIGGER_HOLDOFF_S}")

scope.write(f":WAV:SOUR CHAN{CHANNEL}")
scope.write(":WAV:MODE RAW")
scope.write(":WAV:FORM BYTE")
scope.write(":ACQ:MDEP 12000")

csv_fp = open(csv_file, "w", newline="")
csv_writer = csv.writer(csv_fp)
csv_writer.writerow(["timestamp", "vpp_v", "duration_s", "event_rate_hz", "screenshot_file"])
csv_fp.flush()

last_event_time = None
last_physical_event = 0.0
buffer = []
event_id = 0

print("Armed. Waiting for pulses...\n")

try:
    while not stop_requested:
        scope.write(":SINGLE")

        while not stop_requested:
            if scope.query(":TRIG:STAT?").strip() == "STOP":
                break
            time.sleep(0.002)

        if stop_requested:
            break

        raw = np.array(scope.query_binary_values(":WAV:DATA?", datatype="B"))
        if raw.size < MIN_SAMPLES:
            continue

        now = time.perf_counter()
        if now - last_physical_event < DEAD_TIME_S:
            continue

        yinc = float(scope.query(":WAV:YINC?"))
        yref = float(scope.query(":WAV:YREF?"))
        yorig = float(scope.query(":WAV:YOR?"))
        xinc = float(scope.query(":WAV:XINC?"))

        volts = (raw - yref) * yinc + yorig
        vpp = float(np.max(volts) - np.min(volts))

        state = "idle"
        start_idx = None
        end_idx = None
        for i, v in enumerate(volts):
            if state == "idle" and v < LOW_LEVEL_V:
                state = "active"
                start_idx = i
            elif state == "active" and v > HIGH_LEVEL_V:
                end_idx = i
                break

        duration = float((end_idx - start_idx) * xinc) if start_idx is not None and end_idx is not None else 0.0

        rate = 0.0 if last_event_time is None else 1.0 / (now - last_event_time)
        last_event_time = now
        last_physical_event = now

        timestamp = datetime.now().isoformat()

        scope.write(":STOP")
        scope.write(":DISP:DATA? ON,PNG")
        png = scope.read_raw()

        if png[0:1] == b"#":
            header_len = int(png[1:2])
            data_len = int(png[2:2+header_len])
            png = png[2+header_len:2+header_len+data_len]

        img_name = f"pulse_{event_id:06d}.png"
        with open(img_folder / img_name, "wb") as f:
            f.write(png)

        buffer.append([timestamp, vpp, duration, rate, img_name])

        print(f"Pulse {event_id} | Vpp={vpp:.3f} V | dt={duration:.2e} s | rate={rate:.2f} Hz")

        event_id += 1

        if len(buffer) >= FLUSH_EVERY_N_EVENTS:
            csv_writer.writerows(buffer)
            csv_fp.flush()
            buffer.clear()

except Exception as e:
    print("ERROR:", e)

if buffer:
    csv_writer.writerows(buffer)
    csv_fp.flush()

csv_fp.close()
print("Done. Data and screenshots saved.")
