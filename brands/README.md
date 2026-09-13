# Brand assets

`icon.svg` is the source. The PNGs are rendered from it and follow the naming the
[home-assistant/brands](https://github.com/home-assistant/brands) repository expects,
so they can be submitted there as `custom_integrations/arcane/`:

| File | Size |
| --- | --- |
| `icon.png` | 256x256 |
| `icon@2x.png` | 512x512 |
| `logo.png` | 256x256 |
| `logo@2x.png` | 512x512 |

`custom_components/arcane/brand/icon.png` and `logo.png` are copies of the same
artwork. HACS looks for them there and only falls back to the brands repository when
they are missing, so the integration validates before that submission is accepted.
Home Assistant itself still shows a generic placeholder until it is.

The assets here are original artwork for this project and are not the Arcane project's
own logo.
