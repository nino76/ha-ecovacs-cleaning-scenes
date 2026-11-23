"""Ecovacs button module."""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import logging
from typing import Any, override

from deebot_client.capabilities import (
    Capabilities,
    CapabilityExecute,
    CapabilityExecuteTypes,
    CapabilityLifeSpan,
    DeviceType,
)
from deebot_client.commands import StationAction
from deebot_client.device import Device
from deebot_client.events import LifeSpan

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcovacsConfigEntry
from .const import SUPPORTED_LIFESPANS, SUPPORTED_STATION_ACTIONS
from .controller import QuickCommandsStore
from .entity import (
    EcovacsCapabilityEntityDescription,
    EcovacsDescriptionEntity,
    EcovacsEntity,
)
from .util import get_supported_entities

_LOGGER = logging.getLogger(__name__)

_QUICK_COMMAND_NAME = "clean_V2"
_QUICK_COMMAND_ACTION = "start"
_QUICK_COMMAND_TYPE = "qcClean"
_QUICK_COMMAND_SETTLE_TIMEOUT = 5


@dataclass(kw_only=True, frozen=True)
class EcovacsButtonEntityDescription(
    ButtonEntityDescription,
    EcovacsCapabilityEntityDescription,
):
    """Ecovacs button entity description."""


@dataclass(kw_only=True, frozen=True)
class EcovacsLifespanButtonEntityDescription(ButtonEntityDescription):
    """Ecovacs lifespan button entity description."""

    component: LifeSpan


@dataclass(kw_only=True, frozen=True)
class EcovacsStationActionButtonEntityDescription(ButtonEntityDescription):
    """Ecovacs station action button entity description."""

    action: StationAction


ENTITY_DESCRIPTIONS: tuple[EcovacsButtonEntityDescription, ...] = (
    EcovacsButtonEntityDescription(
        capability_fn=lambda caps: caps.map.relocation if caps.map else None,
        key="relocate",
        translation_key="relocate",
        entity_category=EntityCategory.CONFIG,
    ),
)

STATION_ENTITY_DESCRIPTIONS = tuple(
    EcovacsStationActionButtonEntityDescription(
        action=action,
        key=f"station_action_{action.name.lower()}",
        translation_key=f"station_action_{action.name.lower()}",
    )
    for action in SUPPORTED_STATION_ACTIONS
)


LIFESPAN_ENTITY_DESCRIPTIONS = tuple(
    EcovacsLifespanButtonEntityDescription(
        component=component,
        key=f"reset_lifespan_{component.name.lower()}",
        translation_key=f"reset_lifespan_{component.name.lower()}",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    )
    for component in SUPPORTED_LIFESPANS
)


@dataclass(frozen=True)
class _SceneChanges:
    """Differences between the stored and the incoming scene lists."""

    added: tuple[dict[str, Any], ...]
    updated: tuple[dict[str, Any], ...]
    removed: tuple[str, ...]


def _scene_qcid(scene: Mapping[str, Any]) -> str | None:
    """Return the scene QCID as a stable string, or None if unusable."""
    if (qcid := scene.get("qcid")) is None:
        return None
    value = str(qcid).strip()
    return value or None


def _quick_command_unique_id(did: str, qcid: str) -> str:
    """Return the stable unique id for a scene button."""
    return f"{did}_quick_command_{qcid}"


def _quick_command_payload(qcid: str) -> dict[str, Any]:
    """Return the verified start-scene payload; QCID is always a string."""
    return {
        "act": _QUICK_COMMAND_ACTION,
        "content": {"type": _QUICK_COMMAND_TYPE, "value": str(qcid)},
    }


def _scene_name(scene: Mapping[str, Any], qcid: str) -> str:
    """Derive the displayed name from the current scene data."""
    name = scene.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return f"Quick command {qcid}"


def _reconcile_scenes(
    current: Mapping[str, dict[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
) -> _SceneChanges:
    """Compute added/updated/removed scenes, keyed by QCID.

    Duplicate QCIDs in the incoming list are ignored after the first one, so a
    repeated or redundant reply can never create two entities.
    """
    desired: dict[str, dict[str, Any]] = {}
    for scene in incoming:
        if (qcid := _scene_qcid(scene)) is None or qcid in desired:
            continue
        desired[qcid] = dict(scene)

    return _SceneChanges(
        added=tuple(desired[qcid] for qcid in desired if qcid not in current),
        updated=tuple(
            desired[qcid]
            for qcid in desired
            if qcid in current and current[qcid] != desired[qcid]
        ),
        removed=tuple(qcid for qcid in current if qcid not in desired),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EcovacsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add entities for passed config_entry in HA."""
    controller = config_entry.runtime_data
    entities: list[EcovacsEntity] = get_supported_entities(
        controller, EcovacsButtonEntity, ENTITY_DESCRIPTIONS
    )
    entities.extend(
        EcovacsResetLifespanButtonEntity(
            device, device.capabilities.life_span, description
        )
        for device in controller.devices
        for description in LIFESPAN_ENTITY_DESCRIPTIONS
        if description.component in device.capabilities.life_span.types
    )
    entities.extend(
        EcovacsStationActionButtonEntity(
            device, device.capabilities.station.action, description
        )
        for device in controller.devices
        if device.capabilities.station
        for description in STATION_ENTITY_DESCRIPTIONS
        if description.action in device.capabilities.station.action.types
    )
    async_add_entities(entities)

    managers = [
        EcovacsQuickCommandManager(hass, device, async_add_entities)
        for device in controller.devices
        if device.capabilities.device_type is DeviceType.VACUUM
        and device.capabilities.custom
    ]
    for manager in managers:
        await manager.async_subscribe(controller.quick_commands)
        config_entry.async_on_unload(manager.async_unsubscribe)


class EcovacsButtonEntity(
    EcovacsDescriptionEntity[CapabilityExecute],
    ButtonEntity,
):
    """Ecovacs button entity."""

    entity_description: EcovacsLifespanButtonEntityDescription

    @override
    async def async_press(self) -> None:
        """Press the button."""
        await self._device.execute_command(self._capability.execute())


class EcovacsResetLifespanButtonEntity(
    EcovacsDescriptionEntity[CapabilityLifeSpan],
    ButtonEntity,
):
    """Ecovacs reset lifespan button entity."""

    entity_description: EcovacsLifespanButtonEntityDescription

    @override
    async def async_press(self) -> None:
        """Press the button."""
        await self._device.execute_command(
            self._capability.reset(self.entity_description.component)
        )


class EcovacsStationActionButtonEntity(
    EcovacsDescriptionEntity[CapabilityExecuteTypes[StationAction]],
    ButtonEntity,
):
    """Ecovacs station action button entity."""

    entity_description: EcovacsStationActionButtonEntityDescription

    @override
    async def async_press(self) -> None:
        """Press the button."""
        await self._device.execute_command(
            self._capability.execute(self.entity_description.action)
        )


class EcovacsQuickCommandManager:
    """Create, update and remove the dynamic quick-command buttons.

    Reconciliation is serialized by a manager lock, and the store already
    serializes notifications per device. Two rapid updates therefore cannot
    interleave, create duplicates or resurrect a removed scene.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device: Device,
        async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        """Initialize the manager."""
        self._hass = hass
        self._device = device
        self._async_add_entities = async_add_entities
        self._scenes: dict[str, dict[str, Any]] = {}
        self._entities: dict[str, EcovacsQuickCommandButton] = {}
        self._lock = asyncio.Lock()
        self._unsubscribe: Callable[[], None] | None = None
        self._unloaded = False

    @property
    def did(self) -> str:
        """Return the device identifier."""
        return self._device.device_info["did"]

    async def async_subscribe(self, store: QuickCommandsStore) -> None:
        """Subscribe to scene updates; lock order is store -> manager."""
        self._unsubscribe = await store.async_subscribe(
            self.did, self.async_update_scenes
        )

    @callback
    def async_unsubscribe(self) -> None:
        """Stop listening to scene updates."""
        self._unloaded = True
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    async def async_update_scenes(self, scenes: Sequence[Mapping[str, Any]]) -> None:
        """Reconcile the buttons with the authoritative scene list."""
        if self._unloaded:
            return
        async with self._lock:
            changes = _reconcile_scenes(self._scenes, scenes)

            # Removals first, so a deleted scene cannot reappear because of a
            # later reply based on an older snapshot.
            for qcid in changes.removed:
                await self._async_remove_entity(qcid)

            for scene in changes.updated:
                qcid = _scene_qcid(scene)
                assert qcid is not None
                self._scenes[qcid] = dict(scene)
                self._entities[qcid].async_update_scene(scene)

            added: list[EcovacsQuickCommandButton] = []
            for scene in changes.added:
                qcid = _scene_qcid(scene)
                assert qcid is not None
                entity = EcovacsQuickCommandButton(self._device, qcid, scene)
                self._entities[qcid] = entity
                self._scenes[qcid] = dict(scene)
                added.append(entity)

            if added and not self._unloaded:
                self._async_add_entities(added)

    async def _async_remove_entity(self, qcid: str) -> None:
        """Remove a button from HA, from the registry and from the manager."""
        entity = self._entities.pop(qcid, None)
        self._scenes.pop(qcid, None)
        if entity is None:
            return

        # async_add_entities schedules the real add as a task. If the scene is
        # removed before that task ran, wait for it to settle so the entity is
        # not added afterwards as a ghost.
        if entity.hass is None:
            try:
                await asyncio.wait_for(
                    entity.async_wait_settled(), _QUICK_COMMAND_SETTLE_TIMEOUT
                )
            except TimeoutError:
                _LOGGER.debug(
                    "Timed out waiting for quick-command button %s to settle", qcid
                )

        if (entity_id := entity.entity_id) is not None:
            # Registry first: this sets _removed_from_registry on the entity so
            # async_remove() deletes the state instead of writing unavailable.
            er.async_get(self._hass).async_remove(entity_id)
        if entity.hass is not None:
            await entity.async_remove()


class EcovacsQuickCommandButton(EcovacsDescriptionEntity[Capabilities], ButtonEntity):
    """Button that starts one dynamically discovered quick-command scene."""

    def __init__(
        self,
        device: Device,
        qcid: str,
        scene: Mapping[str, Any],
    ) -> None:
        """Initialize the button."""
        super().__init__(
            device,
            device.capabilities,
            ButtonEntityDescription(
                key=f"quick_command_{qcid}", name=_scene_name(scene, qcid)
            ),
        )
        self._attr_unique_id = _quick_command_unique_id(
            device.device_info["did"], qcid
        )
        self._qcid = qcid
        self._settled = asyncio.Event()
        # Runs both on a normal add and on an aborted add (disabled entity).
        self.async_on_remove(self._settled.set)

    async def async_added_to_hass(self) -> None:
        """Signal that the entity has been added."""
        await super().async_added_to_hass()
        self._settled.set()

    async def async_wait_settled(self) -> None:
        """Wait until the add completed or was aborted."""
        await self._settled.wait()

    @callback
    def async_update_scene(self, scene: Mapping[str, Any]) -> None:
        """Apply updated scene data; the unique id never changes."""
        name = _scene_name(scene, self._qcid)
        if self.entity_description.name != name:
            self.entity_description = ButtonEntityDescription(
                key=self.entity_description.key, name=name
            )
        if self.hass is not None:
            self.async_write_ha_state()

    @override
    async def async_press(self) -> None:
        """Start the scene using the verified payload."""
        await self._device.execute_command(
            self._capability.custom.set(
                _QUICK_COMMAND_NAME, _quick_command_payload(self._qcid)
            )
        )
