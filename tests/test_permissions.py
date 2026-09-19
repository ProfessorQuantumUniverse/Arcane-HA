"""Tests for the API key permissions the options need."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.arcane.api import ArcanePermissionError
from custom_components.arcane.const import (
    CONF_ALLOW_CONTROL,
    CONF_HOST_STATS,
    CONF_MONITOR_CONTAINERS,
    CONF_MONITOR_PROJECTS,
    CONF_MONITOR_RESOURCES,
    CONF_PRUNE_BUTTON,
    CONF_UPDATE_ENTITIES,
    DEFAULT_OPTIONS,
    DOMAIN,
    PRUNE_DANGLING,
)
from custom_components.arcane.permissions import (
    format_permissions,
    required_permissions,
)


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, options: dict | None = None
) -> None:
    """Set up the integration and wait for the platforms."""
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options=options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def test_defaults_need_read_and_control() -> None:
    """The default options need the read and the lifecycle permissions."""
    needed = required_permissions({})

    assert needed.monitoring == [
        "environments:list",
        "containers:list",
        "projects:list",
        "images:list",
        "volumes:list",
        "networks:list",
        "system:read",
        "environments:read",
    ]
    assert needed.control == [
        "containers:start",
        "containers:stop",
        "containers:restart",
        "containers:redeploy",
        "projects:deploy",
        "projects:down",
        "projects:restart",
        "system:upgrade",
    ]


def test_read_only_options_need_no_control() -> None:
    """Turning control off drops every permission that changes something."""
    needed = required_permissions({**DEFAULT_OPTIONS, CONF_ALLOW_CONTROL: False})

    assert needed.control == []
    assert "containers:list" in needed.monitoring


def test_options_only_ask_for_what_they_use() -> None:
    """A trimmed down setup needs a correspondingly short list."""
    needed = required_permissions(
        {
            **DEFAULT_OPTIONS,
            CONF_MONITOR_CONTAINERS: True,
            CONF_MONITOR_PROJECTS: False,
            CONF_MONITOR_RESOURCES: False,
            CONF_UPDATE_ENTITIES: False,
            CONF_HOST_STATS: False,
            CONF_PRUNE_BUTTON: PRUNE_DANGLING,
        }
    )

    assert needed.monitoring == ["environments:list", "containers:list"]
    assert needed.control == [
        "containers:start",
        "containers:stop",
        "containers:restart",
        "system:prune",
    ]


def test_host_stats_alone_need_system_read() -> None:
    """Host statistics come out of the system endpoints as well."""
    needed = required_permissions(
        {**DEFAULT_OPTIONS, CONF_MONITOR_RESOURCES: False, CONF_HOST_STATS: True}
    )

    assert "system:read" in needed.monitoring


def test_format_permissions() -> None:
    """Permissions are rendered as code, and an empty list as a dash."""
    assert format_permissions(["a:b", "c:d"]) == "`a:b`, `c:d`"
    assert format_permissions([]) == "-"


async def test_options_flow_lists_permissions(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """The options offer a page with the permissions the options need."""
    await _setup(hass, mock_config_entry)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "permissions"}
    )

    assert result["type"] is FlowResultType.FORM
    placeholders = result["description_placeholders"]
    assert "`containers:list`" in placeholders["monitoring"]
    assert "`system:upgrade`" in placeholders["control"]
    assert placeholders["missing"] == "-"

    # Submitting the page returns to the menu without changing anything.
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.MENU


async def test_refused_call_is_listed_as_missing(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A refused request names its permission and raises a repair."""
    mock_client.async_get_volume_counts.side_effect = ArcanePermissionError("nope")

    await _setup(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data
    assert coordinator.missing_permissions == ["volumes:list"]

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"missing_permissions_{mock_config_entry.entry_id}"
    )
    assert issue is not None
    assert "`volumes:list`" in issue.translation_placeholders["permissions"]

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "permissions"}
    )
    assert "`volumes:list`" in result["description_placeholders"]["missing"]


async def test_repair_goes_away_once_the_key_is_widened(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A permission that is granted later clears the repair on the next poll."""
    mock_client.async_get_volume_counts.side_effect = ArcanePermissionError("nope")
    await _setup(hass, mock_config_entry)

    issue_id = f"missing_permissions_{mock_config_entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    mock_client.async_get_volume_counts.side_effect = None
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.missing_permissions == []
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_refused_action_names_the_permission(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    """A button press Arcane refuses reports the permission it needed."""
    mock_client.async_container_action.side_effect = ArcanePermissionError("nope")
    await _setup(hass, mock_config_entry)

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.container_homeassistant_restart"},
            blocking=True,
        )

    assert err.value.translation_key == "container_action_forbidden"
    assert err.value.translation_placeholders["permission"] == "containers:restart"

    coordinator = mock_config_entry.runtime_data
    assert coordinator.missing_permissions == ["containers:restart"]
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"missing_permissions_{mock_config_entry.entry_id}"
        )
        is not None
    )
