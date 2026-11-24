# Third-party notices

Lattice is built on the open-source work below. Each component is used under its own license; the
copyright for each belongs to its authors. This list covers what the app depends on at runtime and what
it bundles. Versions are the ones the test suite runs against.

## Bundled in this repository

| Component | Where | License |
|---|---|---|
| [Lucide](https://lucide.dev) icons | `backend/assets/icons/` | ISC (full text in `backend/assets/icons/LICENSE`) |
| [Fluent UI System Icons](https://github.com/microsoft/fluentui-system-icons) | `backend/assets/icons/fluent/` | MIT (full text in `backend/assets/icons/fluent/LICENSE`) |
| Patrick Hand SC (Mariano Diez Gutierrez) | `backend/assets/fonts/` | SIL Open Font License 1.1 (full text in `backend/assets/fonts/LICENSE.txt`) |

## Python packages (installed from `backend/requirements.txt`)

| Package | Version | License |
|---|---|---|
| FastAPI | 0.141 | MIT |
| Uvicorn | 0.52 | BSD-3-Clause |
| Pydantic, pydantic-settings | 2.13, 2.15 | MIT |
| python-dotenv | 1.2 | BSD-3-Clause |
| httpx | 0.28 | BSD-3-Clause |
| OpenAI Python SDK | 3.6 | Apache-2.0 |
| PyJWT (with cryptography) | 2.15 | MIT (cryptography: Apache-2.0 or BSD-3-Clause) |
| Playwright for Python | 1.62 | Apache-2.0 |
| kokoro-onnx | 0.6 | MIT |
| ONNX Runtime | 1.23 | MIT |
| soundfile | 0.14 | BSD-3-Clause |
| gTTS | 2.5 | MIT |
| boto3 (only when object storage is configured) | 1.34+ | Apache-2.0 |

## Models, tools and services used at runtime (not bundled)

| Component | Use | License |
|---|---|---|
| Kokoro-82M voice model (`kokoro-v1.0.onnx`, `voices-v1.0.bin`) | narration | Apache-2.0 |
| Manim Community Edition (render image `manimcommunity/manim:v0.18.1`) | scene rendering | MIT |
| FFmpeg | stitching and probing video | LGPL-2.1+ / GPL depending on the build |
| Google Chrome (headless) | rendering browser scenes and slides | Google Chrome Terms of Service |
| Caddy | HTTPS reverse proxy on the server | Apache-2.0 |
| Bricolage Grotesque, Geist, Geist Mono (Google Fonts) | interface typefaces | SIL Open Font License 1.1 |

The model provider called through the OpenRouter-compatible API is a hosted service used under its own
terms; no model weights from it are included here.
