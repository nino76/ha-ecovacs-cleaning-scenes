"""Ecovacs util functions."""

from collections.abc import Mapping
from enum import Enum
import random
import string
from typing import TYPE_CHECKING, Any, cast

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import slugify

from .entity import (
    EcovacsCapabilityEntityDescription,
    EcovacsDescriptionEntity,
    EcovacsEntity,
)

if TYPE_CHECKING:
    from .controller import EcovacsController


def get_client_device_id(
    hass: HomeAssistant, self_hosted: bool, config: Mapping[str, Any]
) -> str:
    """Get client device id."""
    if device_id := config.get(CONF_DEVICE_ID):
        return cast(str, device_id)
    if self_hosted:
        return f"HA-{slugify(hass.config.location_name)}"

    return "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(8)
    )


def get_supported_entities(
    controller: EcovacsController,
    entity_class: type[EcovacsDescriptionEntity],
    descriptions: tuple[EcovacsCapabilityEntityDescription, ...],
) -> list[EcovacsEntity]:
    """Return all supported entities for all devices."""
    return [
        entity_class(device, capability, description)
        for device in controller.devices
        for description in descriptions
        if (capability := description.capability_fn(device.capabilities))
    ]


@callback
def get_name_key(enum: Enum) -> str:
    """Return the lower case name of the enum."""
    return enum.name.lower()


@callback
def get_options(enum: type[Enum]) -> list[str]:
    """Return the options for the enum."""
    return [get_name_key(option) for option in enum]


@callback
def parse_quick_commands(response: Any) -> list[dict[str, Any]] | None:
    """Parse a getQuickCommand response into the authoritative scene list.

    Return ``None`` when the reply does not have the expected structure, so a
    malformed reply is never mistaken for an authoritative empty list. An
    empty ``data`` array is a valid answer and is returned as ``[]``.
    """
    root = response.get("resp", response) if isinstance(response, dict) else None
    if not isinstance(root, dict):
        return None

    body = root.get("body")
    if not isinstance(body, dict):
        return None

    data = body.get("data")
    if not isinstance(data, list):
        return None
    if not data:
        return []

    first = data[0]
    if not isinstance(first, dict):
        return None

    scenes = first.get("array")
    if not isinstance(scenes, list):
        return None
    # A malformed element must not be silently dropped: dropping every element
    # would turn a bad reply into an authoritative empty list and delete buttons.
    if not all(
        isinstance(scene, dict)
        and scene.get("qcid") is not None
        and str(scene["qcid"]).strip()
        for scene in scenes
    ):
        return None

    # Only the QCID and the displayed name are needed to create, update and
    # remove the scene buttons. Do not retain unrelated robot payload fields
    # in memory or expose them in the vacuum entity attribute.
    return [{"qcid": scene["qcid"], "name": scene.get("name")} for scene in scenes]
