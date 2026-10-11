# Hybrid 0.9.84.2 IVS test candidate

This directory contains the standalone candidate built from the working **0.9.84.1 hybrid**. It adds separate binary sensors for complete, unambiguous Normal IVS rules. Existing aggregate motion sensors, ANPR handling, event subscriptions and config-entry format are preserved.

**Status:** 31 local tests passed. This has not been tested on the live NVR or in the user's Home Assistant runtime. NVR configuration rule IDs must match the IDs in real events. No match is guessed by rule name or array position.

The repository root remains the fork's existing upstream snapshot. Install the candidate through this directory's guarded installer; selecting this repository as a HACS source alone does not install this nested package.

## Download and check from Home Assistant Terminal

Restore the original working hybrid and its pre-merge camera configuration first. Then download this branch into a separate folder:

```bash
mkdir -p /config/dahua_ivs_github
curl -fL 'https://codeload.github.com/alpha520098/dahua/tar.gz/refs/heads/hybrid-ivs-0.9.84.2-candidate' -o /config/dahua_ivs_github/source.tar.gz
tar -xzf /config/dahua_ivs_github/source.tar.gz -C /config/dahua_ivs_github --strip-components=1
bash /config/dahua_ivs_github/hybrid/ivs-0.9.84.2/install_ivs.sh --check
```

This downloads and checks files; it does not install them or restart Home Assistant. The installer refuses versions other than the exact original hybrid 0.9.84.1 and verifies source checksums.

## Apply the test candidate

Once the restored baseline is working and the check passes:

```bash
bash /config/dahua_ivs_github/hybrid/ivs-0.9.84.2/install_ivs.sh --apply
```

The installer saves the current integration and registry snapshot, stops Core, installs five source files, and starts Core. It prints a rollback command. It does not manually alter the registries. Existing selected events must include the relevant IVS event types (typically CrossLineDetection and CrossRegionDetection).

## Validation and review

- [Full instructions and limitations](README.txt)
- [Source patch against the original hybrid](hybrid_ivs.patch)
- [Installer](install_ivs.sh)
- [Rollback script](rollback_ivs.sh)
- [Tests](test_ivs.py)

Run `python3 test_ivs.py` inside this directory on a machine with Python 3.11+ and Bash. HA/network objects are stand-ins. Tests cover ID matching, overlapping rule Stop handling, channel filtering, retained motion/ANPR behavior, source preservation, read-only RPC2 request shape, guarded install, and failure recovery. Hardware verification remains required.
