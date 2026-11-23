# Ecovacs Custom Cleaning Scenes

A complete Home Assistant custom integration that adds dynamic buttons for
saved cleaning scenes to the standard Ecovacs integration.

## What it does

- Discovers saved cleaning scenes with a read-only `getQuickCommand` request at startup.
- Parses replies defensively: a malformed response is ignored, so the last
  known-good scene list and its buttons are kept.
- Creates, renames, updates and removes one button per scene, keyed by the stable
  `qcid` identifier.
- Starts a scene with a verified payload (`clean_V2` / `qcClean`).
- Never starts a cleaning task during discovery.
- Exposes the last scene list in the `quick_commands` attribute of the vacuum entity.
- Refreshes the list with the standard `homeassistant.update_entity` service on
  the vacuum entity.

This repository ships the whole `custom_components/ecovacs` integration, so it
replaces the built-in Ecovacs integration in Home Assistant. It contains no
hardware-profile patch and no model-specific mapping.

## Safety and update handling

- Per-device locks serialise scene updates and subscriber notifications.
- A manager lock orders subscription, reconciliation and entity add/remove.
- Discovery requests are time-limited; timeouts and errors are logged at debug level.
- Duplicate QCIDs are ignored and removals are processed before additions.
- Buttons are removed from the entity registry when a scene disappears.
- Explicit refresh uses `async_update(force=True)`; no periodic polling is added.

## Compatibility

- Home Assistant 2026.11+
- `py-sucks==0.9.11`, `deebot-client==18.7.0` (unchanged from the base integration)
- Requires a robot whose capability profile exposes custom commands
  (`CapabilityCustomCommand`) and support for `getQuickCommand`. Robots without
  it keep working normally, but no scene buttons appear.

Independent from [Ecovacs Model Override](https://github.com/nino76/ecovacs-model-override):
no files, imports or settings are shared. The two integrations use different
domains (`ecovacs` and `ecovacs_model_override`) and can be installed at the same
time. When both are installed, `ecovacs` waits for the model override to finish
setup so the mapping is active before device discovery.

## Installation (Home Assistant Marketplace)

1. In Home Assistant open **Settings → Devices & services → Marketplace** (the three-dot menu).
2. Add `https://github.com/nino76/ha-ecovacs-cleaning-scenes` as a **Custom repository** with category **Integration**.
3. Install **Ecovacs Custom Cleaning Scenes** and restart Home Assistant.
4. Configure your account through the usual **Add Integration → Ecovacs** flow.

Manual install: copy `custom_components/ecovacs/` into `<config>/custom_components/`,
restart and add the Ecovacs integration from the UI.

## Usage

Scene buttons appear as entities under each supported vacuum device. Pressing one
starts that saved cleaning scene. To re-read scenes from the robot, call
`homeassistant.update_entity` on the vacuum entity.

The existing diagnostic log lines in `vacuum.py` are kept unchanged from the
verified implementation.

## Credits

Repository: https://github.com/nino76/ha-ecovacs-cleaning-scenes

Author: nino76

Based on the Home Assistant core Ecovacs integration (code owners @mib1185,
@edenhaus, @Augar) and the `deebot-client` library.

## License

MIT — see `LICENSE`.
