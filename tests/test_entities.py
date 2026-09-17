"""Tests for the Arcane entity platforms."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.update import UpdateEntityFeature
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_SCAN_INTERVAL,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.arcane.api import (
    ArcaneAuthenticationError,
    ArcaneConnectionError,
    ArcanePermissionError,
)
from custom_components.arcane.const import (
    CONF_ALLOW_CONTROL,
    CONF_ENTITY_PREFIX,
    CONF_ENVIRONMENTS,
    CONF_EVENTS,
    CONF_HOST_STATS,
    CONF_MONITOR_PROJECTS,
    CONF_MONITOR_RESOURCES,
    CONF_NEST_CONTAINERS,
    CONF_PRUNE_BUTTON,
    CONF_REDEPLOY_BUTTONS,
    CONF_UPDATE_ENTITIES,
    EVENT_CONTAINER_HEALTH,
    EVENT_CONTAINER_STATE,
    EVENT_PROJECT_STATE,
)
from tests.conftest import CONTAINERS_PAYLOAD, PROJECTS_PAYLOAD


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, options: dict | None = None
) -> None:
    """Set up the integration and wait for the platforms."""
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options=options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_states(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Environments, containers and projects turn into entities."""
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert hass.states.get("sensor.local_containers_running").state == "2"
    assert hass.states.get("sensor.local_containers_stopped").state == "1"
    assert hass.states.get("sensor.local_containers").state == "3"
    assert hass.states.get("sensor.local_container_updates_available").state == "1"
    assert hass.states.get("sensor.local_projects_running").state == "1"
    assert hass.states.get("sensor.local_images").state == "12"
    assert hass.states.get("sensor.local_unused_volumes").state == "1"
    assert hass.states.get("sensor.local_networks").state == "4"
    assert hass.states.get("binary_sensor.local_online").state == STATE_ON

    assert hass.states.get("sensor.container_homeassistant_state").state == "running"
    assert (
        hass.states.get("binary_sensor.container_homeassistant_running").state
        == STATE_ON
    )
    assert (
        hass.states.get("binary_sensor.container_homeassistant_update_available").state
        == STATE_ON
    )
    assert hass.states.get("switch.container_homeassistant").state == STATE_ON
    assert hass.states.get("switch.container_whoami").state == STATE_OFF

    assert hass.states.get("sensor.project_smarthome_status").state == "running"
    assert hass.states.get("sensor.project_smarthome_services_running").state == "2"
    assert hass.states.get("switch.project_smarthome").state == STATE_ON


async def test_docker_version_sensor_is_disabled_by_default(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The Docker version is diagnostic and stays off unless enabled."""
    await _setup(hass, mock_config_entry)

    assert hass.states.get("sensor.local_docker_version") is None


@pytest.mark.parametrize(
    ("service", "action"),
    [("turn_on", "start"), ("turn_off", "stop")],
)
async def test_container_switch(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    service: str,
    action: str,
) -> None:
    """The container switch maps onto the Arcane container actions."""
    await _setup(hass, mock_config_entry)

    await hass.services.async_call(
        "switch",
        service,
        {ATTR_ENTITY_ID: "switch.container_homeassistant"},
        blocking=True,
    )

    mock_client.async_container_action.assert_awaited_once_with("0", "c1ffee", action)


async def test_project_switch_and_button(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Project switches deploy and stop, the button restarts."""
    await _setup(hass, mock_config_entry)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: "switch.project_smarthome"},
        blocking=True,
    )
    mock_client.async_project_action.assert_awaited_once_with("0", "smarthome", "down")

    mock_client.async_project_action.reset_mock()
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.project_smarthome_restart"},
        blocking=True,
    )
    mock_client.async_project_action.assert_awaited_once_with(
        "0", "smarthome", "restart"
    )


async def test_new_container_is_added_on_refresh(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Containers created after setup show up on the next refresh."""
    await _setup(hass, mock_config_entry)
    assert hass.states.get("switch.container_newcomer") is None

    mock_client.async_get_containers.return_value = [
        *mock_client.async_get_containers.return_value,
        {
            "id": "beef",
            "names": ["/newcomer"],
            "image": "alpine:latest",
            "created": 1735689600,
            "state": "running",
            "status": "Up 1 second",
            "labels": {},
        },
    ]
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("switch.container_newcomer").state == STATE_ON


async def test_unreachable_environment_stays_available(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A failing environment is reported as offline, not as a failed refresh."""
    error = ArcaneConnectionError("down")
    for call in (
        mock_client.async_get_containers,
        mock_client.async_get_projects,
        mock_client.async_get_image_counts,
        mock_client.async_get_volume_counts,
        mock_client.async_get_network_counts,
        mock_client.async_get_docker_info,
    ):
        call.side_effect = error

    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("binary_sensor.local_online").state == STATE_OFF
    assert hass.states.get("sensor.local_containers").state == "0"


async def test_missing_permission_only_drops_that_resource(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A key without volumes:list keeps every other entity working."""
    mock_client.async_get_volume_counts.side_effect = ArcanePermissionError("nope")

    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("binary_sensor.local_online").state == STATE_ON
    assert hass.states.get("sensor.local_containers").state == "3"
    assert hass.states.get("sensor.local_volumes").state == "unknown"


async def test_auth_error_triggers_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """An expired API key starts a re-authentication flow."""
    mock_client.async_get_version.side_effect = ArcaneAuthenticationError("expired")
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_unload(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The entry unloads cleanly."""
    await _setup(hass, mock_config_entry)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_update_entity(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The update entity reports the newer image and redeploys on install."""
    await _setup(hass, mock_config_entry)

    state = hass.states.get("update.container_homeassistant_image_update")
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == "2025.1.0"
    assert state.attributes["latest_version"] == "2025.2.0"

    await hass.services.async_call(
        "update",
        "install",
        {ATTR_ENTITY_ID: "update.container_homeassistant_image_update"},
        blocking=True,
    )
    mock_client.async_container_action.assert_awaited_once_with(
        "0", "c1ffee", "redeploy"
    )


async def test_read_only_mode(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """With control switched off only the reporting entities are created."""
    await _setup(hass, mock_config_entry, {CONF_ALLOW_CONTROL: False})

    assert hass.states.get("switch.container_homeassistant") is None
    assert hass.states.get("button.container_homeassistant_restart") is None
    assert (
        hass.states.get("binary_sensor.container_homeassistant_running").state
        == STATE_ON
    )

    update = hass.states.get("update.container_homeassistant_image_update")
    assert update.attributes["supported_features"] == 0


async def test_disabled_resource_polling(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Switching parts off stops both the polling and the entities."""
    await _setup(
        hass,
        mock_config_entry,
        {
            CONF_MONITOR_PROJECTS: False,
            CONF_MONITOR_RESOURCES: False,
            CONF_UPDATE_ENTITIES: False,
        },
    )

    mock_client.async_get_projects.assert_not_called()
    mock_client.async_get_image_counts.assert_not_called()
    assert hass.states.get("switch.project_smarthome") is None
    assert hass.states.get("sensor.local_images") is None
    assert hass.states.get("update.container_homeassistant_image_update") is None
    assert hass.states.get("switch.container_homeassistant").state == STATE_ON


async def test_environment_filter(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Only the selected environments are polled."""
    mock_client.async_get_environments.return_value = [
        {"id": "0", "name": "Local", "status": "online", "enabled": True},
        {"id": "7", "name": "Remote", "status": "online", "enabled": True},
    ]
    await _setup(hass, mock_config_entry, {CONF_ENVIRONMENTS: ["7"]})

    assert hass.states.get("binary_sensor.local_online") is None
    assert hass.states.get("binary_sensor.remote_online").state == STATE_ON


async def test_custom_scan_interval(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The configured interval reaches the coordinator."""
    await _setup(hass, mock_config_entry, {CONF_SCAN_INTERVAL: 300})

    assert mock_config_entry.runtime_data.update_interval == timedelta(seconds=300)


async def test_health_sensor_only_where_docker_reports_health(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Only a container with a health check gains a Healthy sensor."""
    await _setup(hass, mock_config_entry)

    assert hass.states.get("binary_sensor.container_uptime_kuma_healthy").state == (
        STATE_ON
    )
    assert hass.states.get("binary_sensor.container_whoami_healthy") is None
    assert hass.states.get("sensor.local_unhealthy_containers").state == "0"


async def test_device_hierarchy(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A container of a Compose project hangs below that project."""
    await _setup(hass, mock_config_entry)

    registry = dr.async_get(hass)
    devices = {device.name: device for device in registry.devices.values()}

    assert devices["Container homeassistant"].via_device_id == (
        devices["Project smarthome"].id
    )
    assert devices["Project smarthome"].via_device_id == devices["Local"].id
    # A container outside any project stays directly below the environment.
    assert devices["Container whoami"].via_device_id == devices["Local"].id


async def test_prefix_and_nesting_can_be_switched_off(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Without the prefix the devices carry their bare names again."""
    await _setup(
        hass,
        mock_config_entry,
        {CONF_ENTITY_PREFIX: False, CONF_NEST_CONTAINERS: False},
    )

    registry = dr.async_get(hass)
    devices = {device.name: device for device in registry.devices.values()}

    assert "homeassistant" in devices
    assert "Container homeassistant" not in devices
    assert devices["homeassistant"].via_device_id == devices["Local"].id


async def test_host_stats(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Host statistics are polled only when asked for."""
    await _setup(hass, mock_config_entry)
    mock_client.async_get_host_stats.assert_not_called()
    assert hass.states.get("sensor.local_host_cpu") is None

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_HOST_STATS: True}
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.local_host_cpu").state == "12.5"
    assert hass.states.get("sensor.local_host_memory").state == "25.0"
    assert hass.states.get("sensor.local_host_disk").state == "20.0"


async def test_redeploy_and_prune_buttons(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Both extra buttons are opt in and call the right endpoint."""
    await _setup(hass, mock_config_entry)
    assert hass.states.get("button.container_homeassistant_redeploy") is None
    assert hass.states.get("button.local_prune_unused") is None

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_REDEPLOY_BUTTONS: True, CONF_PRUNE_BUTTON: "unused"},
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.container_homeassistant_redeploy"},
        blocking=True,
    )
    mock_client.async_container_action.assert_awaited_once_with(
        "0", "c1ffee", "redeploy"
    )

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.project_smarthome_redeploy"},
        blocking=True,
    )
    mock_client.async_project_action.assert_awaited_once_with(
        "0", "smarthome", "redeploy"
    )

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.local_prune_unused"},
        blocking=True,
    )
    mock_client.async_prune.assert_awaited_once_with("0", unused_images=True)


async def test_events(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """State, crash and health changes reach the event bus."""
    await _setup(hass, mock_config_entry)

    events: list[Event] = []
    for name in (
        EVENT_CONTAINER_STATE,
        EVENT_CONTAINER_HEALTH,
        EVENT_PROJECT_STATE,
    ):
        hass.bus.async_listen(name, events.append)

    crashed = [dict(item) for item in CONTAINERS_PAYLOAD]
    crashed[0]["state"] = "exited"
    crashed[0]["status"] = "Exited (137) 1 second ago"
    crashed[1]["status"] = "Up 26 hours (unhealthy)"
    mock_client.async_get_containers.return_value = crashed
    stopped = [{**PROJECTS_PAYLOAD[0], "status": "stopped"}]
    mock_client.async_get_projects.return_value = stopped

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    by_type = {event.event_type: event.data for event in events}
    assert by_type[EVENT_CONTAINER_STATE]["container"] == "homeassistant"
    assert by_type[EVENT_CONTAINER_STATE]["crashed"] is True
    assert by_type[EVENT_CONTAINER_STATE]["oom_killed"] is True
    assert by_type[EVENT_CONTAINER_STATE]["exit_code"] == 137
    assert by_type[EVENT_CONTAINER_HEALTH]["health"] == "unhealthy"
    assert by_type[EVENT_PROJECT_STATE]["status"] == "stopped"


async def test_events_can_be_switched_off(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """No events are fired when the option is off."""
    await _setup(hass, mock_config_entry, {CONF_EVENTS: False})

    events: list[Event] = []
    hass.bus.async_listen(EVENT_CONTAINER_STATE, events.append)

    stopped = [dict(item) for item in CONTAINERS_PAYLOAD]
    stopped[0]["state"] = "exited"
    mock_client.async_get_containers.return_value = stopped
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert not events


async def test_arcane_update_entity(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Arcane itself reports its own update, ready for the updates panel."""
    await _setup(hass, mock_config_entry)

    state = hass.states.get("update.local_arcane")
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == "1.4.0"
    assert state.attributes["latest_version"] == "1.5.0"
    assert state.attributes["title"] == "Arcane"
    assert state.attributes["release_url"].endswith("/1.5.0")
    assert "Faster project list." in state.attributes["release_summary"]
    # The updates panel only lists entities that can actually be installed.
    assert state.attributes["supported_features"] & UpdateEntityFeature.INSTALL

    assert state.attributes["supported_features"] & UpdateEntityFeature.RELEASE_NOTES

    notes = await hass.services.async_call(
        "update",
        "install",
        {ATTR_ENTITY_ID: "update.local_arcane"},
        blocking=True,
    )
    assert notes is None
    mock_client.async_upgrade.assert_awaited_once_with("0")


async def test_arcane_update_falls_back_to_the_digest(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A digest tracking instance still reads as having an update."""
    mock_client.async_get_version.return_value = {
        "currentVersion": "1.4.0",
        "updateAvailable": True,
        "newestDigest": "sha256:9f8e7d6c5b4a3210fedcba9876543210",
    }
    await _setup(hass, mock_config_entry)

    state = hass.states.get("update.local_arcane")
    assert state.state == STATE_ON
    assert state.attributes["latest_version"] == "9f8e7d6c5b4a"
    # Nothing to show, so the release notes button is not offered either.
    assert not state.attributes["supported_features"] & (
        UpdateEntityFeature.RELEASE_NOTES
    )


async def test_arcane_update_without_an_update(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """An up to date instance stays off and out of the updates panel."""
    mock_client.async_get_version.return_value = {
        "currentVersion": "1.5.0",
        "newestVersion": "1.5.0",
        "updateAvailable": False,
    }
    await _setup(hass, mock_config_entry)

    assert hass.states.get("update.local_arcane").state == STATE_OFF


async def test_container_update_carries_the_image_as_title(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The updates panel shows which image an update is about."""
    await _setup(hass, mock_config_entry)

    state = hass.states.get("update.container_homeassistant_image_update")
    assert state.attributes["title"] == "ghcr.io/home-assistant/home-assistant"


async def test_only_remote_environments_cost_a_version_request(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The local environment reuses the version already fetched."""
    await _setup(hass, mock_config_entry)
    mock_client.async_get_environment_version.assert_not_called()

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    mock_client.async_get_environments.return_value = [
        {"id": "0", "name": "Local", "status": "online", "enabled": True},
        {"id": "7", "name": "Remote", "status": "online", "enabled": True},
    ]
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_client.async_get_environment_version.assert_awaited_once_with("7")
    assert hass.states.get("update.remote_arcane").state == STATE_OFF
    assert hass.states.get("update.local_arcane").state == STATE_ON


async def test_update_entities_can_be_switched_off(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Switching update entities off removes the Arcane one as well."""
    await _setup(hass, mock_config_entry, {CONF_UPDATE_ENTITIES: False})

    assert hass.states.get("update.local_arcane") is None
    assert hass.states.get("update.container_homeassistant_image_update") is None


async def test_read_only_mode_keeps_updates_visible_but_not_installable(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Without control the update still reports, it just cannot be installed."""
    await _setup(hass, mock_config_entry, {CONF_ALLOW_CONTROL: False})

    state = hass.states.get("update.local_arcane")
    assert state.state == STATE_ON
    assert not state.attributes["supported_features"] & UpdateEntityFeature.INSTALL
