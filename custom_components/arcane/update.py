"""Update platform for the Arcane integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ArcaneConfigEntry
from .api import ApiGeneration, ArcaneError, ArcanePermissionError
from .const import CONF_ALLOW_CONTROL, CONF_UPDATE_ENTITIES, DOMAIN, MANUFACTURER
from .entity import ArcaneContainerEntity, ArcaneEnvironmentEntity
from .github import GitHubError, ImageUpdate, async_release_notes
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


@dataclass(frozen=True, slots=True)
class _Notes:
    """What was found about the release notes of one pending update."""

    notes: str | None
    url: str | None


def _text(value: Any) -> str | None:
    """Return a non-empty string from an API reply, or None."""
    return value.strip() if isinstance(value, str) and value.strip() else None


class ArcaneContainerUpdate(ArcaneContainerEntity, UpdateEntity):
    """Report and install a newer image for a container.

    Installing runs Arcane's own updater for the container, the same as the
    update action in the Arcane UI. It applies whatever Arcane found: a new
    digest of a moving tag such as ``latest``, or, for a container whose
    update policy follows versions, the newer tag it writes into the compose
    file. A redeploy would only pull the pinned tag again.

    Release notes come from Arcane 3, which looks up the GitHub release of the
    target version from the image labels. When it has none, for example for a
    new image of ``latest`` that names no version, or on Arcane 2, the
    releases of the GitHub repository the labels name are read directly. They
    are only fetched when the update dialog asks for them, and kept per target
    version.
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
        self._notes = _Notes(None, None)

    @property
    def _target(self) -> tuple[str, str | None, str | None] | None:
        """Return the image, version and digest the pending update is about."""
        container = self.container
        if container is None or not container.update_available:
            return None
        return container.image, container.update_version, container.update_digest

    @property
    def _cached_notes(self) -> _Notes | None:
        """Return what was found for the pending update, if it was looked up."""
        target = self._target
        if target is None or target != self._notes_target:
            return None
        return self._notes

    @property
    def _asks_arcane(self) -> bool:
        """Return whether Arcane can be asked for release notes."""
        return (
            self.coordinator.client.generation is ApiGeneration.V3
            and PERM_IMAGE_UPDATES_READ not in self.coordinator.missing_permissions
        )

    @property
    def _offers_release_notes(self) -> bool:
        """Return whether release notes may exist for the pending update."""
        if self._target is None or (container := self.container) is None:
            return False
        # Once nothing was found for this target, stop offering notes.
        if (cached := self._cached_notes) is not None:
            return cached.notes is not None
        return self._asks_arcane or container.source_repository is not None

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
        if (cached := self._cached_notes) is not None and cached.url:
            return cached.url
        container = self.container
        return container.release_link if container else None

    async def async_release_notes(self) -> str | None:
        """Return the release notes of the version the update installs."""
        if (target := self._target) is None or not self._offers_release_notes:
            return None
        if (cached := self._cached_notes) is not None:
            return cached.notes
        found, complete = await self._async_look_up_notes()
        if found.notes is not None or complete:
            # Kept, so the dialog opening again asks nobody. A lookup that
            # failed on the way is not, so the next one tries again.
            self._notes_target, self._notes = target, found
        # The release link and whether notes are offered may have changed.
        self.async_write_ha_state()
        return found.notes

    async def _async_look_up_notes(self) -> tuple[_Notes, bool]:
        """Ask Arcane, then GitHub, for the notes of the pending update.

        Returns what was found, and whether every source asked answered.
        """
        container = self.container
        assert container is not None
        image, version = container.image, container.update_version
        complete = True
        fallback_url: str | None = None
        if self._asks_arcane:
            try:
                reply = await self.coordinator.client.async_get_release_notes(
                    self.environment_id,
                    image,
                    version=version,
                    digest=container.update_digest,
                )
            except ArcanePermissionError:
                self.coordinator.async_note_denied(PERM_IMAGE_UPDATES_READ)
                reply = {}
            except ArcaneError as err:
                _LOGGER.debug("Arcane has no release notes for %s: %s", image, err)
                reply, complete = {}, False
            if notes := _text(reply.get("notes")):
                return _Notes(notes, _text(reply.get("releaseUrl"))), True
            # Arcane may have read the version from the labels of the new
            # image even though it found no release for it.
            version = version or _text(reply.get("version"))
            fallback_url = _text(reply.get("releaseUrl"))

        if (repository := container.source_repository) is None:
            return _Notes(None, fallback_url), complete
        try:
            found = await async_release_notes(
                async_get_clientsession(self.hass),
                repository,
                ImageUpdate(
                    image=(image_name(image) or image).rpartition("/")[2],
                    tag=container.tag,
                    version=version,
                    # The labels name the installed version even for a moving
                    # tag; a tag update also knows the tag it replaces.
                    installed=container.image_version
                    or (
                        container.installed_version
                        if container.update_version
                        else None
                    ),
                ),
            )
        except GitHubError as err:
            _LOGGER.debug("No release notes on GitHub for %s: %s", image, err)
            return _Notes(None, fallback_url), False
        if found is None:
            return _Notes(None, fallback_url), complete
        return _Notes(found.notes, found.url), True

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
