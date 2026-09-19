# Changelog

Versions follow [semantic versioning](https://semver.org/). Nothing is tagged yet, so a
version is the state of the default branch from the day it landed, which is also what
HACS installs and shows.

## 0.5.0 (2026-09-19)

### Added

- **API key permissions** page under *Configure*. It lists the Arcane permissions the
  options in use need, split into monitoring and control, so a role can be built before
  anything runs into a 403. Options that are off are not listed.
- A repair under *Settings > System > Repairs* whenever Arcane refuses a call, listing
  every permission the API key was turned down for. It clears again once the key carries
  them. The same list is on the permissions page and in the diagnostics download.
- An action Arcane refuses now names the permission it needed instead of reporting a
  bare 403.

## 0.4.0 (2026-09-17)

### Added

- Update entity per environment for the Arcane instance itself, with the installed and
  newest version, the release notes and a link to the release page. Installing asks
  Arcane to pull its own newer image and restart, which needs the `system:upgrade`
  permission.
- Container update entities carry the image reference as their title.

Both kinds appear under **Settings > Updates** once they have an update.

### Fixed

- An Arcane instance that tracks a digest rather than a release reports an update without
  naming a version. The short digest now stands in as the newer version, so the entity no
  longer reads as up to date while an update is waiting.

## 0.3.0 (2026-09-13)

### Added

- Healthy binary sensor per container, for containers that define a health check, and an
  unhealthy container count per environment.
- Host CPU, memory and disk usage per environment, off by default.
- Arcane version as a diagnostic sensor.
- Redeploy button per container and per project, off by default.
- Prune button per environment for unused images, networks and build cache, off by
  default. Containers and volumes are never pruned.
- `arcane_container_state_changed`, `arcane_container_health_changed` and
  `arcane_project_state_changed` on the event bus, with `crashed` and `oom_killed`
  derived from the exit code.
- Device names carry their kind, so a container and a project of the same name no longer
  collide into `_2` suffixed entity IDs. Existing entity IDs are left untouched.
- Containers of a Compose project are nested under that project device.
- The options flow is split into Polling, Entities and Control.
- Brand assets ship inside the integration so HACS validates before the Home Assistant
  brands submission is accepted.

### Fixed

- Deploying a project was reported as failed even when it worked. Arcane answers `up` and
  `redeploy` with a newline delimited log stream rather than a JSON envelope, which the
  client rejected as invalid JSON.

### Security

- The WebSocket handshake followed redirects and replayed the API key header while doing
  so. A socket reached through a redirect is now rejected.
- The log stream is read in capped chunks and split by hand, so a reply without newlines
  cannot grow the buffer without bound.
- Reconfigure no longer fills the stored API key into the form. An empty field keeps the
  key that is already stored.

## 0.2.0 (2026-09-12)

### Added

- Options flow for the poll interval, which environments to follow, whether containers,
  projects and resource counts are polled at all, whether image update entities are
  created, and a read only mode. Switching a part off also stops the API calls behind it.
- Update entity per container that redeploys it onto the newer image.
- Options to include internal and hidden containers.
- Logo and brand assets.

### Fixed

- Replies were read with a single read, which returns only the first chunk, so a
  container list larger than one chunk failed to parse.

### Security

- Redirects are no longer followed, so the API key cannot be replayed against the host a
  redirect points at.
- Every dynamic path segment is percent escaped and the URL is passed through as encoded.
- Only http and https addresses are accepted; addresses carrying credentials, a query or
  a fragment are refused.
- A missing permission no longer triggers a re-authentication loop: only HTTP 401 asks
  for a new key, HTTP 403 leaves that part of the data empty.
- Container and project actions are checked against an allow list, API keys are rejected
  when empty or when they carry header separators, replies are size capped, and error
  bodies are truncated and stripped of control characters.

## 0.1.0 (2026-09-12)

### Added

- First version. Config flow with URL, API key and SSL verification, plus reauth and
  reconfigure.
- A device per environment, container and Compose project, with containers and projects
  added and removed while Home Assistant runs.
- Sensors for container, project, image, volume and network counts, image storage,
  container state and project status.
- Binary sensors for environment connectivity, running state and available image updates.
- Switches to start and stop containers and to bring projects up and down, and restart
  buttons for both.
- Diagnostics, English and German translations, HACS metadata and CI.
