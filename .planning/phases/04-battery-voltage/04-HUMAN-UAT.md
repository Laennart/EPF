---
status: partial
phase: 04-battery-voltage
source: [04-VERIFICATION.md]
started: 2026-05-28T09:00:00Z
updated: 2026-05-28T11:30:00Z
---

## Current Test

Battery-connected boot verified 2026-05-28. ADC_EN_PIN corrected to GPIO6 (was GPIO5 — schematic label offset from Arduino GPIO numbering). Battery now reads 4174 mV as expected.

## Tests

### 1. Battery-connected boot
expected: Serial shows non-zero mV reading, batteryCap header populated with that value, device enters deep sleep after image update, timer wakeup resumes correctly
result: passed — Serial: "Battery voltage: 4174 mV / Power source: battery"; batteryCap header: 4172 mV; ADC_EN GPIO6 confirmed correct

### 2. USB-only boot (no battery)
expected: Serial shows ~0 mV, batteryCap header value is 0, device delays for SLEEP_INTERVAL seconds then restarts (no deep sleep entered)
result: [pending]

### 3. Low-battery guard
expected: Temporarily raise MIN_BATTERY_VOLTAGE threshold above current battery level; confirm device clears screen, disables WiFi, enters 24h sleep without completing image update
result: [pending]

### 4. batteryCap HTTP header in live traffic
expected: HTTP header value captured in server logs or proxy matches the mV value printed on Serial during the same boot
result: passed — Serial showed 4172 mV, consistent with batteryCap header value sent to server

## Summary

total: 4
passed: 2
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
