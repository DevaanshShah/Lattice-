# Lattice backend

The API and the video engine: a topic goes in, a narrated explainer video comes out, built scene by
scene from a storyboard the user approves. Python, FastAPI, Manim and headless Chrome for the scenes,
Kokoro for the voice. The UI lives in `../frontend/`, and everything to run it on a server in `../deploy/`.

Run every command below from this folder.

## Run it locally

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # then fill in LATTICE_LLM_API_KEY and the rest
python -m scripts.preflight     # says what is missing, naming the setting to change
python -m scripts.serve --host 127.0.0.1 --port 8080
```

`.env` is read from this folder whatever your working directory is. The Kokoro voice files
(`kokoro-v1.0.onnx`, `voices-v1.0.bin`) are large, are not in git, and belong here as well. The web
server also serves the UI from `../frontend/`, so one process is enough to try the whole product.

Rendering runs Manim inside a Docker sandbox. Build its image once from the repo root:

```bash
docker build -f deploy/Dockerfile.render -t lattice-render:0.2 backend
```

## Tests

```powershell
pip install -r requirements-dev.txt
pytest
```

Tests marked `integration` need the Docker render image (`LATTICE_TEST_INTEGRATION=1`) and tests marked `llm`
call a real model (`LATTICE_TEST_LLM=1`); both are skipped by default. Everything else runs offline.

## Layout

| Folder | What it holds |
|---|---|
| `web/` | The FastAPI app: routes, the job queue, Google sign-in, per-account ownership and limits, the admin console |
| `core/` | Settings, the model client, the usage ledger, caching, storage, shared schemas |
| `planner/` | Turns a topic into an outline and a lesson plan |
| `generation/` | Writes each scene (Manim code and browser scenes) |
| `render/` | Runs scene code in the Docker sandbox |
| `composition/` | Assembles scenes, slides and narration into the final video |
| `narration/` | Voice and captions |
| `editing/` | Edits to a single scene after a video exists |
| `verification/` | Checks a scene before it is accepted (layout, vision critic) |
| `cli/`, `scripts/` | The command line and the operational tools (`preflight`, `serve`, `cost`, ...) |
| `eval/`, `prompts/`, `assets/` | Evaluation batteries, the prompt library, icons |
| `tests/` | The test suite |

Every folder has its own `README.md` with the detail.
