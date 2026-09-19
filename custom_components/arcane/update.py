"""Update platform for the Arcane integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ArcaneConfigEntry
from .api import ArcaneError
from .const import CONF_ALLOW_CONTROL, CONF_UPDATE_ENTITIES, DOMAIN, MANUFACTURER
from .entity import ArcaneContainerEntity, ArcaneEnvironmentEntity
from .helpers import action_error, async_setup_entities
from .models import ArcaneVersion
from .permissions import PERM_CONTAINERS_REDEPLOY, PERM_SYSTEM_UPGRADE

PARALLEL_UPDATES = 1

# Home Assistant stores the release summary as a state attribute, which is
# capped at 255 characters.
MAX_RELEASE_SUMMARY = 255

CONTAINER_UPDATE = UpdateEntityDescription(
    key="image_update",
    translation_key="image_update",
)

ARCANE_UPDATE = UpdateEntityDescription(
    key="arcane_update",
    translation_key="arcane_update",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArcaneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Arcane update entities."""
    coordinator = entry.runtime_data
    if not coordinator.option(CONF_UPDATE_ENTITIES):
        return

    async_setup_entities(
        coordinator,
        async_add_entities,
        environments=lambda environment_id: [
            ArcaneInstanceUpdate(coordinator, environment_id, ARCANE_UPDATE)
        ],
        containers=lambda environment_id, name: [
            ArcaneContainerUpdate(coordinator, environment_id, name, CONTAINER_UPDATE)
        ],
    )


def _summary(notes: str | None) -> str | None:
    """Return release notes short enough to live in a state attribute."""
    if not notes:
        return None
    text = notes.strip()
    if len(text) <= MAX_RELEASE_SUMMARY:
        return text
    return f"{text[: MAX_RELEASE_SUMMARY - 1].rstrip()}…"


class ArcaneContainerUpdate(ArcaneContainerEntity, UpdateEntity):
    """Report and install a newer image for a container.

    Installing runs Arcane's redeploy, which pulls the image the container was
    created from and recreates the container with the same configuration.
    """

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Return whether this entity may install the update."""
        if self.coordinator.option(CONF_ALLOW_CONTROL):
            return UpdateEntityFeature.INSTALL
        return UpdateEntityFeature(0)

    @property
    def title(self) -> str | None:
        """Return the image this update is about."""
        if (container := self.container) is None:
            return None
        return container.image.rsplit(":", 1)[0] if container.image else None

    @property
    def installed_version(self) -> str | None:
        """Return the version the container currently runs."""
        return self.container.installed_version if self.container else None

    @property
    def latest_version(self) -> str | None:
        """Return the newest version Arcane found for the image."""
        return self.container.latest_version if self.container else None

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Pull the newer image and recreate the container."""
        if (container := self.container) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="container_not_found",
                translation_placeholders={"name": self.container_name},
            )
        try:
            await self.coordinator.client.async_container_action(
                self.environment_id, container.id, "redeploy"
            )
        except ArcaneError as err:
            raise action_error(
                self.coordinator,
                err,
                permission=PERM_CONTAINERS_REDEPLOY,
                action_key="container_action",
                placeholders={"action": "redeploy", "name": self.container_name},
            ) from err
        await self.coordinator.async_request_refresh()


class ArcaneInstanceUpdate(ArcaneEnvironmentEntity, UpdateEntity):
    """Report and install a newer version of Arcane itself.

    Installing asks Arcane to pull its own newer image and restart, so the
    instance is briefly unreachable afterwards.
    """

    _attr_title = MANUFACTURER

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Return what this entity offers beyond reporting a version."""
        features = UpdateEntityFeature(0)
        version = self._version
        if version is not None and version.release_notes:
            features |= UpdateEntityFeature.RELEASE_NOTES
        if self.coordinator.option(CONF_ALLOW_CONTROL):
            features |= UpdateEntityFeature.INSTALL
        return features

    @property
    def _version(self) -> ArcaneVersion | None:
        """Return the version state of this environment's Arcane instance."""
        return self.environment.arcane_version if self.environment else None

    @property
    def available(self) -> bool:
        """Return whether Arcane reported a version for this environment."""
        return super().available and self._version is not None

    @property
    def installed_version(self) -> str | None:
        """Return the version Arcane currently runs."""
        return self._version.installed if self._version else None

    @property
    def latest_version(self) -> str | None:
        """Return the newest Arcane version available."""
        return self._version.latest if self._version else None

    @property
    def release_url(self) -> str | None:
        """Return the release page of the newest version."""
        return self._version.release_url if self._version else None

    @property
    def release_summary(self) -> str | None:
        """Return the beginning of the release notes."""
        return _summary(self._version.release_notes if self._version else None)

    async def async_release_notes(self) -> str | None:
        """Return the full release notes for the more info dialog."""
        return self._version.release_notes if self._version else None

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Ask Arcane to upgrade itself."""
        try:
            await self.coordinator.client.async_upgrade(self.environment_id)
        except ArcaneError as err:
            raise action_error(
                self.coordinator,
                err,
                permission=PERM_SYSTEM_UPGRADE,
                action_key="upgrade",
                placeholders={
                    "name": self.environment.name if self.environment else ""
                },
            ) from err
        await self.coordinator.async_request_refresh()
