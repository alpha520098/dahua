# Dahua NVR regression: working hybrid 0.9.84.1 vs 0.10.23

## Reproduced outcome

Hardware: DHI-NVR5216-16HP-XI/Pro with multiple configured channels.

- The user's hybrid 0.9.84.1 updates detection sensors in Home Assistant.
- Installing official 0.10.23 stopped the user's detection sensors working.
- Restoring this exact hybrid package, with the same NVR and Home Assistant configuration, restored normal detection.

This establishes a regression for this installation. It does not, by itself, identify the single offending change. The hybrid is a working reference, and should not be dismissed as an ineffective workaround.

Archive: `dahua_hybrid_anpr_0.9.84.1.tar.gz`

SHA-256: `cb1efbefdbceb516390af3ac06b5d3a5f127c622fee0e4da18c6ae9156968138`

The archive is preserved unchanged. Its installer uses `python3`, which is absent from the user's Home Assistant Terminal environment; the user restored the contained `dahua` directory manually. Do not use installer success or failure as evidence of the event-stream behaviour.

## Code differences that matter

1. The hybrid opens a CGI event stream for each configured channel. In 0.10.23, `DahuaHostEventStream` holds one shared stream per host and routes events by their `index`. This is the main behavioural difference for an NVR whose channels all stopped working.
2. The hybrid adds `FaceDetection`, `Traffic`, `TrafficJunction`, and `TrafficSnapshot` to each coordinator's subscription even when absent from the saved selection. In 0.10.23, `self.events = events`. This can explain Face/Traffic differences; it does not alone explain loss of Human/Vehicle where those were selected.
3. In 0.10.23, `codes=[All]` is only selected when the union of selected events is strictly larger than the largest individual entry's event list. When all channels use identical event lists, this gate is false. An NVR with identical selections therefore does not exercise the advertised `All` subscription.
4. When `All` is selected, 0.10.23 filters events locally before routing them. `DERIVES_INTO` covers CrossLine/CrossRegion to SmartMotionHuman/Vehicle, but the actual event path still needs a live NVR check.

The `translate_event_code` implementation is substantially similar in the hybrid and 0.10.23. Do not label it the cause without a trace showing that an event reached its channel and failed to update a selected sensor.

## Recommended isolation and fix

Keep the working hybrid available for rollback. On a test install of 0.10.23, record the resolved event selection for each channel and the shared stream's actual attach codes. The current diagnostics include `resolved_events`, stream `attached_events`, registered channels, listener keys, and recent routed events. The missing piece is logging the raw `Code` and `index` **before** the host filter:

```python
# DahuaHostEventStream.on_receive(), inside `for event in events:`,
# immediately before `if self._using_all_events ...`.
_LOGGER.debug(
    "Dahua routing: host=%s code=%s index=%s using_all=%s "
    "requested=%s registered_channels=%s",
    self._address,
    event.get("Code"),
    event.get("index"),
    self._using_all_events,
    sorted(self._events),
    sorted(self._by_channel),
)
```

Interpret one real Human and Vehicle event:

- No raw event: inspect the actual attach codes and NVR stream response. As a controlled test, subscribe with `All` for a multi-channel host even when event selections are identical; retain local filtering. This changes one condition without altering routing.
- Raw event present but no matching registered channel: correct the NVR channel/index mapping.
- Matching channel receives raw event, but no sensor update: inspect saved event selection, listener keys, action, and translation/dispatch.
- If `All` still fails with correct routing, compare the single shared connection with the hybrid's per-channel streams and consider an explicit, opt-in NVR compatibility mode rather than forcing multiple connections on every installation.

For Face/Traffic, ensure the saved selection includes those four event names or migrate existing selections deliberately. Do not silently force them for all users as a general solution.

Any proposed fix should be checked on this NVR with Human, Vehicle, Face, Traffic, and existing binary-sensor automations before describing the regression as resolved.
