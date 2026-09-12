"""Tests for the Arcane entity platforms."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.arcane.api import (
    ArcaneAuthenticationError,
    ArcaneConnectionError,
    ArcanePermissionError,
)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the integration and wait for the platforms."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_states(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Environments, containers and projects turn into entities."""
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert hass.states.get("sensor.local_containers_running").state == "1"
    assert hass.states.get("sensor.local_containers_stopped").state == "1"
    assert hass.states.get("sensor.local_containers").state == "2"
    assert hass.states.get("sensor.local_container_updates_available").state == "1"
    assert hass.states.get("sensor.local_projects_running").state == "1"
    assert hass.states.get("sensor.local_images").state == "12"
    assert hass.states.get("sensor.local_unused_volumes").state == "1"
    assert hass.states.get("sensor.local_networks").state == "4"
    assert hass.states.get("binary_sensor.local_online").state == STATE_ON

    assert hass.states.get("sensor.homeassistant_state").state == "running"
    assert hass.states.get("binary_sensor.homeassistant_running").state == STATE_ON
    assert (
        hass.states.get("binary_sensor.homeassistant_update_available").state
        == STATE_ON
    )
    assert hass.states.get("switch.homeassistant").state == STATE_ON
    assert hass.states.get("switch.whoami").state == STATE_OFF

    assert hass.states.get("sensor.smarthome_status").state == "running"
    assert hass.states.get("sensor.smarthome_services_running").state == "2"
    assert hass.states.get("switch.smarthome").state == STATE_ON


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
        {ATTR_ENTITY_ID: "switch.homeassistant"},
        blocking=True,
    )

    mock_client.async_container_action.assert_awaited_once_with("0", "c1ffee", action)


async def test_project_switch_and_button(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Project switches deploy and stop, the button restarts."""
    await _setup(hass, mock_config_entry)

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: "switch.smarthome"}, blocking=True
    )
    mock_client.async_project_down.assert_awaited_once_with("0", "smarthome")

    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.smarthome_restart"},
        blocking=True,
    )
    mock_client.async_project_restart.assert_awaited_once_with("0", "smarthome")


async def test_new_container_is_added_on_refresh(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Containers created after setup show up on the next refresh."""
    await _setup(hass, mock_config_entry)
    assert hass.states.get("switch.newcomer") is None

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

    assert hass.states.get("switch.newcomer").state == STATE_ON


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
    assert hass.states.get("sensor.local_containers").state == "2"
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
