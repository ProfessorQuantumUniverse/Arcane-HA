"""Tests for the Arcane config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.arcane.api import (
    ArcaneAuthenticationError,
    ArcaneConnectionError,
    ArcanePermissionError,
)
from custom_components.arcane.const import DOMAIN

USER_INPUT = {
    "url": "http://192.168.1.10:3552/",
    "api_key": "test-key",
    "verify_ssl": True,
}


async def test_user_flow(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """A valid URL and API key create an entry with a normalized URL."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "192.168.1.10"
    assert result["data"]["url"] == "http://192.168.1.10:3552"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ArcaneAuthenticationError("nope"), "invalid_auth"),
        (ArcaneConnectionError("down"), "cannot_connect"),
        (ArcanePermissionError("forbidden"), "insufficient_permissions"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, mock_client: AsyncMock, error: Exception, reason: str
) -> None:
    """Connection problems are shown on the form and can be retried."""
    mock_client.async_get_version.side_effect = error

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": reason}

    mock_client.async_get_version.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_url_aborts(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A second entry for the same instance is rejected."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Re-authentication stores the new API key."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "new-key"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["api_key"] == "new-key"


async def test_reconfigure_flow(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """Reconfiguration can move the entry to another address."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"url": "https://arcane.example.com", "verify_ssl": False},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["url"] == "https://arcane.example.com"
    # An empty key field keeps the key that is already stored.
    assert mock_config_entry.data["api_key"] == "test-key"


async def test_invalid_url_is_rejected(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """Anything that is not a plain http(s) address is refused."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={**USER_INPUT, "url": "ftp://192.168.1.10"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_url"}
    mock_client.async_get_version.assert_not_called()


async def test_url_with_credentials_is_rejected(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """Userinfo in the address would end up in logs, so it is refused."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={**USER_INPUT, "url": "http://admin:hunter2@192.168.1.10:3552"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_url"}


async def test_options_flow_polling(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The polling section is stored and reloads the entry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "polling"}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval": 120,
            "environments": ["0"],
            "monitor_containers": True,
            "monitor_projects": False,
            "monitor_resources": True,
            "host_stats": False,
            "include_internal": True,
            "include_hidden": False,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options["scan_interval"] == 120
    assert mock_config_entry.options["monitor_projects"] is False
    # Untouched sections keep their defaults.
    assert mock_config_entry.options["allow_control"] is True
    assert hass.states.get("switch.project_smarthome").state == STATE_UNAVAILABLE


async def test_options_flow_control(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The control section can put the integration into read only mode."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "control"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "allow_control": False,
            "redeploy_buttons": False,
            "prune_button": "off",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options["allow_control"] is False
    # The entry reloaded without the control platforms, so the switch is gone
    # and only its restored registry entry is left behind.
    assert hass.states.get("switch.container_homeassistant").state == STATE_UNAVAILABLE
