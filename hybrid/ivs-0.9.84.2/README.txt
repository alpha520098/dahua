Dahua hybrid 0.9.84.2 — IVS binary-sensor TEST CANDIDATE
Prepared 12 October 2026 from the original working 0.9.84.1 archive.

STATUS
31 local tests pass. Python syntax and Bash syntax are checked.
This has NOT been run inside your Home Assistant instance or on your NVR.
Treat it as a test candidate. Preserve the original 0.9.84.1 package.

WHAT IT ADDS
One motion binary sensor for each complete, unambiguous Normal IVS rule.
Names follow the configured rule name; identity uses the stable rule Id and
the hybrid's existing serial/channel identity. Reordering or renaming a rule
does not change its unique ID. Existing entities keep their original IDs.

Each rule sensor reports detection activity: Start turns it on and Stop
turns it off. It does not report whether the IVS rule is enabled, and it does
not enable or disable anything on a camera. Disabled rules can be discovered
but do not normally produce activity. Pulse-only rules are not supported by
this candidate. Normal rules with missing/duplicate IDs or missing Type are
not guessed or exposed.

Tripwire/intrusion rules of the same event code can overlap. A code-level
Stop clears all the rules activated by that code, preserving each rule's
last direction/object metadata. A Stop with missing rule data also clears
the active rules of that code.

READS AND COMPATIBILITY
Direct cameras: existing CGI VideoAnalyseRule read.
Identified NVR/DVR/XVR: per-channel RPC2 RemoteVideoAnalyseRule read with
onlyLocal=false and the exact zero-based channel. Requests are read-only,
serialized per host, and use isolated login/logout sessions with timeouts.
The event-stream method and existing subscription selection are unchanged.

IMPORTANT: the integration's selected events must include the IVS rule's
event type, typically CrossLineDetection or CrossRegionDetection, or All.
This package does not automatically alter your event selections. Preserve
your existing events when enabling any additional IVS event type.

Discovery runs in a config-entry background task and cannot block startup.
A failed optional rule read does not remove the existing motion/ANPR sensors.
A recorder identified only as Generic RTSP takes the direct-camera path;
if it exposes no readable rules, additional discovery work will be needed.

Some Dahua NVR APIs report different rule IDs. This candidate requires the
event's RuleID/RuleId to match both the discovered Id and its event type.
It never falls back to array index or rule name. An unmatched event produces
a warning. A hardware capture is required to prove matching on your NVR.

PRESERVED
The existing DahuaEventSensor and DahuaAuthorizedVehicleBinarySensor classes,
ANPR handler, human/vehicle translation, event timestamps, and stream method
are unchanged. config_flow.py is byte-identical to the original hybrid.
The package introduces no channel merge or config-entry migration.
It does not manually write Home Assistant registries. Home Assistant itself
will register the additional IVS entities in the normal way.

BEFORE INSTALLATION
Finish the 1.2.0 rollback, including the saved pre-merge registry restore.
Confirm normal human detection works on 0.9.84.1 first.
The installer refuses 1.2.0 and refuses a hybrid with modified source files.
Do not bypass that check; a refusal means the actual installed source needs
comparison before it can safely receive this candidate.

INSTALLATION
Place dahua_hybrid_ivs_0.9.84.2_candidate.tar.gz under /config when you can
transfer files. Then, in Terminal & SSH:

  mkdir -p /config/dahua_ivs_candidate
  tar -xzf /config/dahua_hybrid_ivs_0.9.84.2_candidate.tar.gz \
    -C /config/dahua_ivs_candidate --strip-components=1
  bash /config/dahua_ivs_candidate/install_ivs.sh --check

The check verifies baseline and payload checksums and makes no changes.
When the working baseline is confirmed and the check passes:

  bash /config/dahua_ivs_candidate/install_ivs.sh --apply

The script stages the changes, stops Core, rechecks the baseline, backs up
the existing integration and .storage, installs only the changed source
files, and starts Core. Python is not required in the SSH add-on.
Home Assistant's interface may disconnect while Core is stopped; the SSH
add-on's terminal process continues. The original package remains untouched.
The script prints the exact backup directory and rollback command.

LIVE VERIFICATION
1. Confirm manifest version 0.9.84.2 and check Home Assistant startup logs.
2. Confirm existing Smart Motion Human/Vehicle and your security automations.
3. Confirm the new IVS rule sensors appear on the existing camera devices.
4. Trigger one configured tripwire/intrusion rule. Only its rule sensor should
   turn on alongside any existing aggregate sensor. It should clear on Stop.
5. Trigger two rules of the same type together and check that both clear.
6. If no new sensors appear or none activate, inspect the discovery warnings
   and capture the actual rule configuration and dahua_event_received payload.
   Do not remap IDs by guessing. A targeted follow-up may be necessary.

ROLLBACK
Run the exact rollback command printed by the installer. It restores the
integration code saved before applying this candidate and restarts Core.
It retains the current registries because this candidate does not migrate
their format. Newly created IVS entities may remain listed as unavailable;
existing detection entities retain their original identifiers.
The stored registry snapshot is a recovery checkpoint, not an instruction
to overwrite all registries during a routine candidate rollback.

LOCAL VALIDATION
On a machine with Python 3.11+ and Bash, from this extracted directory:

  python3 test_ivs.py

31 tests cover discovery, duplicate/missing IDs, channel isolation,
concurrent Start/Stop behavior, unknown IDs, malformed IVS payloads,
raw hybrid event replay, retained aggregate human/vehicle callbacks,
ANPR event delivery, unchanged source methods, background discovery,
read-only RPC2 request shape, installer refusal, backup/rollback, and
recovery after a simulated file-swap failure.
Network and HA objects in these tests are stand-ins. They do not prove full
Home Assistant runtime compatibility, real RPC2 authentication, firmware
behavior, or the equality of your NVR's configuration and event rule IDs.

FILES
dahua/: full candidate integration; installer overlays only five files.
hybrid_ivs.patch: source diff against the original 0.9.84.1 package.
baseline_checksums.sha256: required installed source checksums.
candidate_checksums.sha256: payload integrity checks.
install_ivs.sh / rollback_ivs.sh: guarded installation and code rollback.
test_ivs.py / test_baseline/: local tests and original-source test fixtures.
preservation_checks.json: original AST/source hashes for review.

UPSTREAM REFERENCES
https://github.com/rroller/dahua/blob/1.2.0/custom_components/dahua/binary_sensor.py
https://github.com/rroller/dahua/blob/1.2.0/custom_components/dahua/ivs.py
https://github.com/rroller/dahua/blob/1.2.0/custom_components/dahua/coordinator.py
https://github.com/rroller/dahua/blob/1.2.0/custom_components/dahua/rpc2.py
https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/config_entries.py
