<img src="brands/icon.png" alt="" width="96" align="left" hspace="16">

# Arcane for Home Assistant

A Home Assistant integration for [Arcane](https://github.com/getarcaneapp/arcane), the
modern Docker management UI. It brings your containers and Compose projects into Home
Assistant as devices you can watch and control, comparable to what the Portainer
integration does, but built on Arcane's own API.

<br clear="left">

## What you get

One device per environment, one per container and one per Compose project.

### Environment device

| Entity | Type | Notes |
| --- | --- | --- |
| Online | binary sensor | Whether Arcane can reach the environment |
| Containers / Containers running / Containers stopped | sensor | Live counts |
| Container updates available | sensor | Containers whose image has a newer version |
| Projects / Projects running | sensor | Compose project counts |
| Images / Unused images / Image storage | sensor | Image usage from Arcane |
| Volumes / Unused volumes / Networks | sensor | Volume and network usage |
| Docker version | sensor | Diagnostic, disabled by default |

### Container device

| Entity | Type | Notes |
| --- | --- | --- |
| *(container name)* | switch | On starts, off stops the container |
| Image update | update | Shows the newer image and installs it with a redeploy |
| Running | binary sensor | |
| Update available | binary sensor | From Arcane's image update check |
| State | sensor | `running`, `exited`, `paused`, and so on |
| Status | sensor | The human readable Docker status |
| Image | sensor | Diagnostic |
| Created | sensor | Diagnostic, disabled by default |
| Restart | button | |

### Compose project device

| Entity | Type | Notes |
| --- | --- | --- |
| *(project name)* | switch | On runs `up`, off runs `down` |
| Running | binary sensor | On while at least one service runs |
| Update available | binary sensor | |
| Status | sensor | `running`, `partially running`, `stopped`, and so on |
| Services / Services running | sensor | |
| Restart | button | |

Containers and projects that appear or disappear in Arcane are added and removed while
Home Assistant keeps running.

## Requirements

- Home Assistant 2025.2 or newer
- An Arcane instance reachable from Home Assistant
- An Arcane API key

## Installation

### HACS

1. In HACS, open the three dot menu and choose **Custom repositories**.
2. Add `https://github.com/ProfessorQuantumUniverse/Arcane-HA` with category **Integration**.
3. Install **Arcane** and restart Home Assistant.

### Manual

Copy `custom_components/arcane` into your Home Assistant `config/custom_components/`
directory and restart Home Assistant.

## Setup

1. In Arcane, go to **Settings > API keys** and create a key.
2. In Home Assistant, go to **Settings > Devices & services > Add integration** and pick
   **Arcane**.
3. Enter the address of your Arcane instance (for example `http://192.168.1.10:3552`)
   and the API key.

The address must be the one Arcane is actually served on. Redirects are not followed on
purpose, so that the API key is never replayed against another host. If setup reports a
redirect, use the address the redirect points at.

### API key permissions

Read only monitoring needs:

`environments:list`, `containers:list`, `projects:list`, `images:list`, `volumes:list`,
`networks:list`, `system:read`

Add these for the switches, buttons and update installs:

`containers:start`, `containers:stop`, `containers:restart`, `containers:redeploy`,
`projects:deploy`, `projects:down`, `projects:restart`

A key without the action permissions still works. The entities are created and the
actions fail with a clear error. Only `environments:list` is required for setup to
succeed; every other missing permission just leaves that part of the data empty.

## Options

Open the integration and choose **Configure**.

| Option | Default | What it does |
| --- | --- | --- |
| Update interval | 30 s | How often Arcane is polled, between 10 and 3600 seconds |
| Environments | all | Restrict the integration to specific environments |
| Containers | on | Create the per container devices and the container counts |
| Compose projects | on | Create the per project devices and the project counts |
| Images, volumes and networks | on | Poll the usage counts and the Docker version |
| Image update entities | on | Offer the per container update entity |
| Allow control from Home Assistant | on | Turn off for a read only setup: no switches, buttons or update installs |
| Include internal containers | off | Also expose containers Arcane marks as internal |
| Include hidden containers | off | Also expose containers hidden in the Arcane interface |

Turning parts off also stops the matching API calls, so a large host can be trimmed down
to just what you use.

## Notes on security

- The API key is sent in the `X-Api-Key` header, never in a URL, and is redacted from
  diagnostics downloads.
- Only `http://` and `https://` addresses are accepted. Addresses that carry credentials
  are rejected, because they would end up in log lines.
- Redirects are not followed, so a redirect cannot make Home Assistant hand the API key
  to a different host.
- Certificate verification can be switched off for a self signed certificate. Home
  Assistant then logs a warning at startup, because the connection carrying the API key
  is no longer authenticated. Prefer a trusted certificate or plain HTTP on a network
  you control.
- Give the key only the permissions you need. The read only option above pairs well with
  a key that holds no action permissions at all.

## Notes on behaviour

- Every selected environment is polled, including remote agents. An unreachable
  environment is reported as offline instead of failing the whole update, and a
  permission the key lacks only empties that part of the data.
- Container entities are keyed by container name, so they survive a redeploy that gives
  the container a new ID.
- Stopping a Compose project runs `down`, which removes its containers. The container
  entities for that project disappear until it is deployed again.
- Installing a container image update runs Arcane's redeploy: it pulls the image the
  container was created from and recreates the container with the same configuration.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest
```
