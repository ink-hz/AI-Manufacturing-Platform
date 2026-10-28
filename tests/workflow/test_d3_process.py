import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from .d3.process import ProofTimeout, run_owned


def test_proof_deadline_kills_only_its_own_child_group(tmp_path):
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    pid_file = tmp_path / "child.pid"
    child = "import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    parent = "import subprocess,sys,time,signal; p=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); signal.signal(signal.SIGTERM,lambda *args:(p.wait(timeout=2),sys.exit(0))); print('runner started',flush=True); time.sleep(30)"
    try:
        with pytest.raises(ProofTimeout) as expired:
            run_owned([sys.executable, "-c", parent, child, str(pid_file)], timeout=0.3, grace=3)
        assert "runner started" in expired.value.details["stdout"]
        assert sentinel.poll() is None
        child_pid = int(pid_file.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=3)
