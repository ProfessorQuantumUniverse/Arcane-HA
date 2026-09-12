"""Tests for the Arcane config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_USER
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
        {"url": "https://arcane.example.com", "api_key": "k", "verify_ssl": False},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["url"] == "https://arcane.example.com"
