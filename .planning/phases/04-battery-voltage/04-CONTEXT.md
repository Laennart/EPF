# Phase 4: Battery Voltage - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Restore battery voltage monitoring removed in Phase 1. The scope is:
- Read battery voltage via ADC on the XIAO ESP32-S3 Plus
- Detect whether device is powered by battery or USB
- Re-enable deep sleep when running on battery (remove the Phase 1 TODO stub)
- On USB power: skip deep sleep, instead wait the server-specified interval and refresh in a loop
- Send battery voltage to the server as the `batteryCap` HTTP header (mV, same as original)
- Suppress or disable the TP4054 charge LED when no battery is connected (if a GPIO path exists; researcher must verify)

**Server-side is already complete** — `app.py` already handles the `batteryCap` header, stores `last_battery_voltage`, performs piecewise linear interpolation against `BATTERY_LEVELS`, and displays % in the settings UI. No server changes needed.

</domain>

<decisions>
## Implementation Decisions

### Battery Voltage Reading
- **D-01:** Use ADC to read battery voltage, multiply by 2 for voltage divider, same as original
- **D-02:** Use a multi-sample average (original used 50 samples with 5ms delay) to reduce noise
- **D-03:** Send voltage as `batteryCap` HTTP header in mV (integer) — matches existing server handler at app.py:861
- **D-04:** The correct ADC GPIO for XIAO ESP32-S3 Plus is **unknown — researcher must verify from Seeed schematic**. Original code used `analogReadMilliVolts(0)` (GPIO0). XIAO ESP32-S3 Plus may use a different pin or require an enable pin to power the voltage divider.

### USB vs Battery Detection
- **D-05:** Detect USB vs battery by reading the ADC voltage — if voltage exceeds a "no battery" threshold (to be determined by researcher), treat as USB-only power
- **D-06:** On **USB power**: skip deep sleep entirely. After displaying image, wait the server-specified sleep duration (`sleepDuration` from `/sleep` endpoint), then call `setup()` equivalent or loop without sleeping.
- **D-07:** On **battery power**: use `esp_deep_sleep_start()` as originally designed — restores the full `hibernate()` implementation

### Low Battery Protection
- **D-08:** Keep original threshold: if battery voltage < 3050 mV (3.05V), enter deep sleep for 24 hours
- **D-09:** On low battery: clear screen, disconnect WiFi, then sleep 24h (same as original)

### Charge LED
- **D-10:** The flashing LED is the **TP4054 charge indicator LED** (not the user/status LED on GPIO21)
- **D-11:** Researcher must check XIAO ESP32-S3 Plus schematic to determine if the CHG/CHRG pin or a PROG pin is wired to a GPIO. If a software path exists, disable the LED when no battery is detected. If hardware-only, document as known limitation.

### Claude's Discretion
- Exact GPIO pin number for battery ADC (researcher verifies from schematic)
- Whether to use `esp_sleep_enable_timer_wakeup` with `GPIO_NUM_2` as originally configured, or update wakeup pin
- USB idle loop implementation details (delay vs lightweight task loop)
- ADC attenuation setting (original did not set attenuation; may need `analogSetAttenuation(ADC_11db)` for full range)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Current Firmware
- `epd7in3e/epd7in3e.ino` — Current firmware; contains `hibernate()` stub with TODO, no battery code
- `epd7in3e/config.h` — GPIO pin defines, sleep constants (`SLEEP_INTERVAL`, `WAKEUP_PIN`, `WAKEUP_LEVEL`)

### Server Battery Infrastructure (already complete)
- `app.py` lines 563–629 — `BATTERY_LEVELS` table and `calculate_battery_percentage()` function
- `app.py` lines 857–864 — `batteryCap` header reading in `/download` endpoint

### Original Battery Implementation (reference for restoration)
- Original code from git commit `8a000e1:Arduino/epd7in3e.ino` contains:
  - `checkVoltage()` method — ADC read, 3.05V threshold check
  - `downloadImage()` battery header section — 50-sample average, `analogReadMilliVolts(0)` × 2
  - `setup()` low-battery branch — clear screen, WiFi off, 24h sleep

### External Hardware Reference
- Seeed XIAO ESP32-S3 Plus schematic — researcher must look up to confirm battery ADC GPIO and CHG LED control path
- TP4054 datasheet — for CHG pin behavior (open-drain, indicates charging state)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `hibernate(int sleepDuration = 0)` in `epd7in3e.ino:279` — already exists, currently stubbed; just needs implementation restored
- `CONFIG_PIN`, `WAKEUP_PIN`, `SLEEP_INTERVAL` in `config.h` — existing constants; battery ADC pin will be added here

### Established Patterns
- Hardware constants defined in `config.h` with `#define` — battery ADC pin and min voltage threshold follow this pattern
- Multi-sample ADC average (50 samples, 5ms delay) — from original code, prevents noise spikes from single reads
- `preferences.getString("SERVER_BASE_URL")` pattern — config read from NVS at runtime

### Integration Points
- `downloadImage()` — battery voltage header added before `http.GET()`, exactly as original
- `setup()` — `checkVoltage()` called before `epaperManager.begin()`, same as original flow
- `hibernate()` — replace TODO stub with real `esp_deep_sleep_start()` path for battery mode; add USB wait-loop path

</code_context>

<specifics>
## Specific Ideas

- The original `checkVoltage()` used a single ADC read (not averaged) for the low-voltage guard. The averaged read was only used for the header. This distinction should be preserved or noted.
- Deep sleep wakeup is via `GPIO_NUM_2` (RTC-capable) with `ESP_GPIO_WAKEUP_GPIO_LOW` — already defined in `config.h`. This must remain unchanged.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 04-battery-voltage*
*Context gathered: 2026-05-28*
