# Brand assets

The artwork is Arcane's own logo, taken from
[getarcaneapp/arcane](https://github.com/getarcaneapp/arcane) (BSD-3-Clause):
`backend/resources/images/logo.svg` is the mark, `logo-full.svg` the wordmark. Both are
kept here as `icon.svg` and `logo.svg` and the PNGs are rendered from them.

| File | Size | From |
| --- | --- | --- |
| `icon.png` | 256x256 | `icon.svg` |
| `icon@2x.png` | 512x512 | `icon.svg` |
| `logo.png` | 1045x256 | `logo.svg` |
| `logo@2x.png` | 2090x512 | `logo.svg` |

The same four PNGs also sit in `custom_components/arcane/brand/`. Home Assistant 2026.3
and newer read them from there, which is why the integration shows the right logo without
waiting on a [home-assistant/brands](https://github.com/home-assistant/brands) pull
request. The copies in this folder follow the naming that repository expects under
`custom_integrations/arcane/`, so they can be submitted as they are for older Home
Assistant versions.
