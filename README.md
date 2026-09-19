<img src="brands/icon.png" alt="" width="120" align="left" hspace="18" vspace="6">

# Arcane for Home Assistant

Watch and control your Docker containers and Compose projects from Home Assistant,
through [Arcane](https://github.com/getarcaneapp/arcane).

<br clear="left">

[![HACS](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)
[![Release](https://img.shields.io/github/v/release/ProfessorQuantumUniverse/Arcane-HA?display_name=tag&sort=semver)](https://github.com/ProfessorQuantumUniverse/Arcane-HA/releases)
[![Validate](https://github.com/ProfessorQuantumUniverse/Arcane-HA/actions/workflows/validate.yml/badge.svg)](https://github.com/ProfessorQuantumUniverse/Arcane-HA/actions/workflows/validate.yml)
[![Tests](https://github.com/ProfessorQuantumUniverse/Arcane-HA/actions/workflows/tests.yml/badge.svg)](https://github.com/ProfessorQuantumUniverse/Arcane-HA/actions/workflows/tests.yml)

You get a device per Arcane environment, per container and per Compose project, with
switches to start and stop them, buttons to restart and redeploy, sensors for the state
and the counts, and update entities that appear under **Settings > Updates** when a
newer image is waiting.

## Requirements

Home Assistant 2025.2 or newer, an Arcane instance it can reach, and an Arcane API key.

## Install

**HACS:** open the three dot menu, choose **Custom repositories**, add
`https://github.com/ProfessorQuantumUniverse/Arcane-HA` with category **Integration**,
install **Arcane** and restart.

**By hand:** copy `custom_components/arcane` into your `config/custom_components/` and
restart.

## Set up

1. In Arcane, create an API key under **Settings > API keys**.
2. In Home Assistant, go to **Settings > Devices & services > Add integration** and pick
   **Arcane**.
3. Enter the address of your instance, for example `http://192.168.1.10:3552`, and the
   key.

Use the address Arcane is actually served on. Redirects are deliberately not followed, so
the API key is never handed to another host. If setup complains about a redirect, use the
address it points at.

### API key permissions

The integration works out what your setup needs and tells you: open it and choose
**Configure > API key permissions**. Copy that list into the role behind the key under
**Settings > Roles** in Arcane. Turning an option off drops its permissions from the
list.

Monitoring needs `environments:list`, `containers:list`, `projects:list`, `images:list`,
`volumes:list`, `networks:list` and `system:read`. Controlling things adds
`containers:start`, `containers:stop`, `containers:restart`, `containers:redeploy`,
`projects:deploy`, `projects:down` and `projects:restart`. Pruning needs `system:prune`
and upgrading Arcane itself needs `system:upgrade`.

Only `environments:list` is required. A key without the rest still sets up; the parts it
cannot reach stay empty and actions fail with an error naming the permission. Whenever
Arcane refuses a call, the permission lands in a repair under
**Settings > System > Repairs**, so a key that is too narrow says so.

## Entities

### Environment

| Entity | Type | Notes |
| --- | --- | --- |
| Online | binary sensor | Whether Arcane reaches the environment |
| Containers, running, stopped | sensor | Live counts |
| Container updates available | sensor | Containers with a newer image |
| Unhealthy containers | sensor | Failing health checks |
| Projects, Projects running | sensor | |
| Images, Unused images, Image storage | sensor | |
| Volumes, Unused volumes, Networks | sensor | |
| Arcane | update | Upgrades the Arcane instance itself |
| Host CPU, memory, disk | sensor | Off by default |
| Docker version, Arcane version | sensor | Diagnostic, disabled by default |
| Prune unused | button | Off by default |

### Container

| Entity | Type | Notes |
| --- | --- | --- |
| *(container name)* | switch | Starts and stops it |
| Image update | update | Installs by redeploying onto the newer image |
| Running, Update available | binary sensor | |
| Healthy | binary sensor | Only with a health check defined |
| State, Status | sensor | `running`, `exited`, `paused` and so on |
| Image, Created | sensor | Diagnostic |
| Restart | button | |
| Redeploy | button | Off by default |

### Compose project

| Entity | Type | Notes |
| --- | --- | --- |
| *(project name)* | switch | On runs `up`, off runs `down` |
| Running, Update available | binary sensor | |
| Status | sensor | `running`, `partially running`, `stopped` and so on |
| Services, Services running | sensor | |
| Restart | button | |
| Redeploy | button | Off by default |

Containers appear as child devices of their Compose project, and containers and projects
that come and go in Arcane are added and removed while Home Assistant keeps running.

## Options

Open the integration and choose **Configure**.

**Polling:** how often Arcane is polled (30 s by default, 10 to 3600), which
environments to follow, and whether containers, Compose projects, resource counts and
host statistics are polled at all. Internal and hidden containers are skipped unless you
ask for them. Switching a part off also stops the API calls behind it, which keeps a big
host manageable.

**Entities:** update entities, health sensors, device name prefixes, nesting containers
under their project, and firing events.

**Control:** whether Home Assistant may control anything at all, plus the redeploy and
prune buttons, which are off by default.

### Device names

A container and a project often share a name, and Home Assistant builds entity IDs from
the device name, so the second one would only get `_2` suffixed IDs. With the prefix on,
you get `Container kopia` and `Project kopia`, so `switch.container_kopia` and
`switch.project_kopia`. Existing entity IDs are never rewritten, so an upgrade keeps
whatever it already has.

## Updates

Container updates and the Arcane instance itself both show up under
**Settings > Updates**, next to core and add-on updates. Installing a container update
runs Arcane's redeploy. Installing the Arcane update asks Arcane to pull its own newer
image and restart, so everything here goes unavailable for a moment.

An entity only appears in that panel while it has an update and can install it, so with
control turned off the entities still report versions but stay out of the way.

## Events

With events on, these fire on the bus and work as automation triggers:

| Event | Data |
| --- | --- |
| `arcane_container_state_changed` | `container`, `state`, `previous_state`, `exit_code`, `crashed`, `oom_killed`, `environment`, `environment_id` |
| `arcane_container_health_changed` | `container`, `health`, `previous_health`, `environment`, `environment_id` |
| `arcane_project_state_changed` | `project`, `project_id`, `status`, `previous_status`, `environment`, `environment_id` |

`crashed` means a running container stopped with a non zero exit code, and `oom_killed`
narrows that to exit code 137, the fingerprint of an out of memory kill. Nothing fires
for the first update after a restart or for a container that has just appeared.

```yaml
automation:
  - triggers:
      - trigger: event
        event_type: arcane_container_state_changed
        event_data:
          crashed: true
    actions:
      - action: notify.mobile_app
        data:
          message: "{{ trigger.event.data.container }} crashed with exit code {{ trigger.event.data.exit_code }}"
```

## Good to know

**Pruning** removes unused images, unused networks and the build cache. Containers and
volumes are never touched, because both hold state you cannot pull back. The option picks
how far it goes: no button at all, dangling images only, or every unused image. A button
in Home Assistant has no confirmation dialog, so leave it off unless you want one press
to act immediately.

**Host statistics** are off by default. Arcane only offers them over a WebSocket and
sends the current sample right after the handshake, so the integration opens a socket,
takes one sample per update and closes it again. Per container CPU and memory are not
available: Arcane wants one socket per container and refuses more than five at a time.

**Security.** The API key travels in the `X-Api-Key` header, never in a URL, and is
redacted from diagnostics. Only `http://` and `https://` addresses are accepted, and
addresses carrying credentials are rejected because they end up in log lines. Redirects
are not followed. You can switch certificate verification off for a self signed
certificate, but Home Assistant will warn at startup, so prefer a trusted certificate or
plain HTTP on a network you control.

**Behaviour.** Every selected environment is polled, remote agents included; one that is
unreachable reports as offline instead of failing the whole update. Container entities
are keyed by name, so they survive a redeploy that changes the container ID. Stopping a
project runs `down`, which removes its containers, so those entities disappear until it
is deployed again. A health sensor is added when the container reports a health check at
the moment it is discovered; one that gains a check later picks it up after a reload.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest
```

### Releasing

The version lives in `custom_components/arcane/manifest.json` and HACS reads it from
there. A release is that version, tagged:

1. Bump `version` in the manifest and add the matching `## X.Y.Z` section to
   `CHANGELOG.md`.
2. Run `python scripts/release.py check vX.Y.Z` to confirm the three agree.
3. Merge, then push the tag. The release workflow rechecks, runs the tests and publishes
   the GitHub release with that changelog section as its notes.

HACS installs the newest published release, so a tag that was never released stays
invisible.
