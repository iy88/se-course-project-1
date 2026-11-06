"""Execute Jenkins' activation shell with fake SSH; never contact a server."""

import codecs
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RELEASE = "a" * 40 + "-42"
BACKUP = "/var/backups/se-course-project1/predeploy-probe"


def shell_body():
    text = (ROOT / "Jenkinsfile").read_text()
    stage = text.index("stage('Activate Production Release')")
    body = re.search(r"sh\s+'''(.*?)'''", text[stage:], re.DOTALL).group(1)
    # Groovy's triple-single-quoted literal processes backslash escapes before
    # passing this text to the shell. Test the actual resulting shell program.
    return codecs.decode(body, "unicode_escape")


def run_activation(tmp_path, mode, release=RELEASE):
    workspace = tmp_path / "workspace"
    artifacts = workspace / "release-artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "release.txt").write_text(f"release_id={release}\n")
    binary = tmp_path / "bin"
    binary.mkdir()
    probe = tmp_path / "ssh.json"
    ssh = binary / "ssh"
    ssh.write_text(
        f"#!{sys.executable}\nimport json,os,sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['ACTIVATION_PROBE']).write_text(json.dumps({"
        "'args':sys.argv[1:], 'script':sys.stdin.read()}))\n"
    )
    ssh.chmod(0o700)
    script = tmp_path / "activate.sh"
    script.write_text(shell_body())
    env = {**os.environ, "WORKSPACE": str(workspace), "DEPLOY_MODE": mode,
           "PRODUCTION_BACKUP_DIR": BACKUP, "ACTIVATION_PROBE": str(probe),
           "PATH": str(binary) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")}
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True,
                            text=True, timeout=10, check=False)
    return result, probe


@pytest.mark.parametrize("mode", ["combined", "split"])
def test_each_topology_uses_the_versioned_unprivileged_activator(tmp_path, mode):
    result, path = run_activation(tmp_path, mode)
    assert result.returncode == 0, result.stderr
    probe = json.loads(path.read_text())
    assert probe["args"][-3:] == [RELEASE, BACKUP, mode]
    assert ".venv/bin/python ../deploy/activate.py" in probe["script"]
    assert '--mode "$mode"' in probe["script"]
    assert "sudo -n /usr/local/sbin/se-course-project1-activate" not in probe["script"]


def test_invalid_topology_never_reaches_ssh(tmp_path):
    result, path = run_activation(tmp_path, "split; unexpected-command")
    assert result.returncode != 0
    assert not path.exists()


def test_invalid_release_never_reaches_ssh(tmp_path):
    result, path = run_activation(tmp_path, "combined", release="invalid-release")
    assert result.returncode != 0
    assert not path.exists()
