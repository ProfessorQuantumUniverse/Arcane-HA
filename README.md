# Arcane for Home Assistant

A Home Assistant integration for [Arcane](https://github.com/getarcaneapp/arcane), the
modern Docker management UI. It brings your containers and Compose projects into Home
Assistant as devices you can watch and control — comparable to what the Portainer
integration does, but built on Arcane's own API.

## What you get

The integration talks to Arcane's REST API and creates one device per environment, one
per container and one per Compose project.

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
| Running | binary sensor | |
| Update available | binary sensor | From Arcane's image update check |
| State | sensor | `running`, `exited`, `paused`, … |
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
| Status | sensor | `running`, `partially running`, `stopped`, … |
| Services / Services running | sensor | |
| Restart | button | |

Containers and projects that appear or disappear in Arcane are added and removed while
Home Assistant keeps running. Data is polled every 30 seconds.

## Requirements

- Home Assistant 2025.2 or newer
- An Arcane instance reachable from Home Assistant
- An Arcane API key

## Installation

### HACS (recommended)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ProfessorQuantumUniverse/Arcane-HA` with category **Integration**.
3. Install **Arcane** and restart Home Assistant.

### Manual

Copy `custom_components/arcane` into your Home Assistant `config/custom_components/`
directory and restart Home Assistant.

## Setup

1. In Arcane, go to **Settings → API keys** and create a key.
2. In Home Assistant, go to **Settings → Devices & services → Add integration** and pick
   **Arcane**.
3. Enter the URL of your Arcane instance (for example `http://192.168.1.10:3552`) and the
   API key. Turn off *Verify SSL certificate* if Arcane uses a self-signed certificate.

### API key permissions

Read-only monitoring needs:

`environments:list`, `containers:list`, `projects:list`, `images:list`, `volumes:list`,
`networks:list`, `system:read`

Add these for the switches and buttons:

`containers:start`, `containers:stop`, `containers:restart`, `projects:deploy`,
`projects:down`, `projects:restart`

A key without the action permissions still works — the entities are created and the
actions fail with a clear error.

## Notes

- Every environment Arcane knows about is polled, including remote agents. An
  unreachable environment is reported as offline instead of failing the whole update.
- Container entities are keyed by container name, so they survive a redeploy that gives
  the container a new ID.
- Stopping a Compose project runs `down`, which removes its containers. The container
  entities for that project disappear until it is deployed again.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest
```
