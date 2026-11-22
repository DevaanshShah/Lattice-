"""M7 / FR-23 — hardened sandbox. Unit-level: the pure command builders carry the caps, and the
wall-clock path kills + reports cleanly. Real containment (fork bomb / net egress) is integration
(`lattice render-sandbox tests/fixtures/...`), not a unit test."""
import subprocess

import pytest

from render import sandbox


@pytest.mark.unit
def test_hardening_args_default_caps_and_no_network():
    args = sandbox.hardening_args()
    assert "--rm" in args
    assert "--network=none" in args                 # no egress
    for flag in ("--memory", "--cpus", "--pids-limit"):
        assert flag in args                          # resource caps + fork-bomb containment
    # --pids-limit value is the configured cap
    assert args[args.index("--pids-limit") + 1] == str(sandbox.settings.render_pids_limit)


@pytest.mark.unit
def test_hardening_args_network_opt_in_drops_isolation():
    assert "--network=none" not in sandbox.hardening_args(network=True)


@pytest.mark.unit
def test_hardening_args_name_enables_killability():
    args = sandbox.hardening_args(name="lattice-xyz")
    assert "--name" in args and args[args.index("--name") + 1] == "lattice-xyz"


@pytest.mark.unit
def test_read_only_adds_tmpfs(monkeypatch):
    monkeypatch.setattr(sandbox.settings, "render_read_only", True)
    monkeypatch.setattr(sandbox.settings, "render_tmpfs_size", "128m")
    args = sandbox.hardening_args()
    assert "--read-only" in args
    assert "--tmpfs" in args and "/tmp:rw,size=128m" in args


@pytest.mark.unit
def test_explicit_user_when_configured(monkeypatch):
    monkeypatch.setattr(sandbox.settings, "render_user", "1000:1000")
    args = sandbox.hardening_args()
    assert "--user" in args and args[args.index("--user") + 1] == "1000:1000"


@pytest.mark.unit
def test_build_command_is_hardened_and_renders_scene(tmp_path):
    cmd = sandbox.build_command(tmp_path, "scene.py", "GeneratedScene", quality="preview")
    assert cmd[:2] == ["docker", "run"]
    assert "--network=none" in cmd and "--memory" in cmd and "--pids-limit" in cmd
    assert "manim" in cmd and "scene.py" in cmd and "GeneratedScene" in cmd
    assert f"{tmp_path.resolve().as_posix()}:/manim" in cmd      # work dir mounted for outputs


@pytest.mark.unit
def test_build_python_command_runs_untrusted_file_under_caps(tmp_path):
    cmd = sandbox.build_python_command(tmp_path, "hostile.py", name="lattice-s")
    assert cmd[:2] == ["docker", "run"]
    assert "--network=none" in cmd and "--pids-limit" in cmd     # caps contain it, not the host
    assert cmd[-2:] == ["python", "hostile.py"]


@pytest.mark.unit
def test_render_wallclock_timeout_kills_and_reports(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=1)

    killed = {}
    monkeypatch.setattr(sandbox.subprocess, "run", boom)
    monkeypatch.setattr(sandbox, "_kill_container", lambda name: killed.setdefault("name", name))

    res = sandbox.render(tmp_path, "scene.py", "GeneratedScene", timeout=1)
    assert res.timed_out and res.returncode == 124 and not res.ok
    assert killed["name"].startswith("lattice-render-")           # the container was killed, not left to linger


@pytest.mark.unit
def test_cli_routes_render_sandbox_subcommand(monkeypatch):
    import cli.__main__ as cli
    seen = {}
    monkeypatch.setattr("scripts.render_sandbox.main", lambda argv: (seen.update(argv=argv), 0)[1])
    rc = cli.main(["render-sandbox", "tests/fixtures/fork_bomb.py", "--timeout", "5"])
    assert rc == 0 and seen["argv"] == ["tests/fixtures/fork_bomb.py", "--timeout", "5"]
