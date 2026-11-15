"""Update platform for the Arcane integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ArcaneConfigEntry
from .api import ApiGeneration, ArcaneError, ArcanePermissionError
from .const import CONF_ALLOW_CONTROL, CONF_UPDATE_ENTITIES, DOMAIN, MANUFACTURER
from .entity import ArcaneContainerEntity, ArcaneEnvironmentEntity
from .helpers import action_error, async_setup_entities
from .models import ArcaneVersion, image_name
from .permissions import (
    PERM_IMAGE_UPDATES_READ,
    PERM_SYSTEM_UPGRADE,
    container_update_permission,
)

if TYPE_CHECKING:
    from .coordinator import ArcaneCoordinator

_LOGGER = logging.getLogger(__name__)

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

    Installing runs Arcane's own updater for the container, the same as the
    update action in the Arcane UI. It applies whatever Arcane found: a new
    digest of a moving tag such as ``latest``, or, for a container whose
    update policy follows versions, the newer tag it writes into the compose
    file. A redeploy would only pull the pinned tag again.

    Release notes come from Arcane 3, which looks up the GitHub release of the
    target version from the image labels. They are only fetched when the
    update dialog asks for them, and kept per target version.
    """

    def __init__(
        self,
        coordinator: ArcaneCoordinator,
        environment_id: str,
        container_name: str,
        description: UpdateEntityDescription,
    ) -> None:
        """Initialize the update entity."""
        super().__init__(coordinator, environment_id, container_name, description)
        self._notes_target: tuple[str, str | None, str | None] | None = None
        self._notes: dict[str, Any] = {}

    @property
    def _target(self) -> tuple[str, str | None, str | None] | None:
        """Return the image, version and digest the pending update is about."""
        container = self.container
        if container is None or not container.update_available:
            return None
        return container.image, container.update_version, container.update_digest

    @property
    def _cached_notes(self) -> dict[str, Any] | None:
        """Return the release notes fetched for the pending update, if any."""
        target = self._target
        if target is None or target != self._notes_target:
            return None
        return self._notes

    @property
    def _offers_release_notes(self) -> bool:
        """Return whether release notes may exist for the pending update."""
        if (
            self._target is None
            or self.coordinator.client.generation is not ApiGeneration.V3
            or PERM_IMAGE_UPDATES_READ in self.coordinator.missing_permissions
        ):
            return False
        # Once Arcane said it has no notes for this target, stop offering them.
        cached = self._cached_notes
        return cached is None or bool(cached.get("notes"))

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Return what this entity offers beyond reporting a version."""
        features = UpdateEntityFeature(0)
        if self.coordinator.option(CONF_ALLOW_CONTROL):
            features |= UpdateEntityFeature.INSTALL
        if self._offers_release_notes:
            features |= UpdateEntityFeature.RELEASE_NOTES
        return features

    @property
    def release_url(self) -> str | None:
        """Return the release page of the update, or the image's releases."""
        cached = self._cached_notes or {}
        if (url := cached.get("releaseUrl")) and isinstance(url, str):
            return url
        container = self.container
        return container.release_link if container else None

    async def async_release_notes(self) -> str | None:
        """Return the release notes of the version the update installs."""
        if (target := self._target) is None or not self._offers_release_notes:
            return None
        if (cached := self._cached_notes) is not None:
            return cached.get("notes") or None
        image, version, digest = target
        try:
            notes = await self.coordinator.client.async_get_release_notes(
                self.environment_id, image, version=version, digest=digest
            )
        except ArcanePermissionError:
            self.coordinator.async_note_denied(PERM_IMAGE_UPDATES_READ)
            self.async_write_ha_state()
            return None
        except ArcaneError as err:
            # Not kept, so the next time the dialog opens asks again.
            _LOGGER.debug("No release notes for %s: %s", image, err)
            return None
        self._notes_target, self._notes = target, notes
        # The release link and whether notes are offered may have changed.
        self.async_write_ha_state()
        text = notes.get("notes")
        return text.strip() if isinstance(text, str) and text.strip() else None

    @property
    def title(self) -> str | None:
        """Return the image this update is about."""
        if (container := self.container) is None:
            return None
        return image_name(container.image)

    @property
    def installed_version(self) -> str | None:
        """Return the version the container currently runs."""
        return self.container.installed_version if self.container else None

    @property
    def latest_version(self) -> str | None:
        """Return the newest version Arcane found for the image."""
        return self.container.latest_version if self.container else None

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Return whether Arcane found an update for the image.

        The versions are often digests, which cannot be ordered, so Arcane's
        own verdict decides instead of a comparison of the two.
        """
        return self.container is not None and self.container.update_available

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Let Arcane apply the update it found for the container."""
        if (container := self.container) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="container_not_found",
                translation_placeholders={"name": self.container_name},
            )
        client = self.coordinator.client
        try:
            await client.async_update_container(self.environment_id, container.id)
        except ArcaneError as err:
            raise action_error(
                self.coordinator,
                err,
                permission=container_update_permission(client.generation),
                action_key="container_update",
                placeholders={"name": self.container_name},
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

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Return whether Arcane offers an update of itself.

        A digest standing in for the newest version cannot be ordered against
        a release number, so Arcane's own verdict decides.
        """
        return self._version is not None and self._version.update_available

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
