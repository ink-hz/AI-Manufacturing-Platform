"""Bounded ownership of a runner and all inherited child process group members."""

import os
import signal
import subprocess


class ProofTimeout(TimeoutError):
    def __init__(self, process, timeout, stdout, stderr):
        super().__init__(f"D3 private host runner exceeded {timeout}s; owned process group terminated")
        self.details = {"owned_process_group": process.pid, "deadline_seconds": timeout, "returncode": process.returncode, "stdout": stdout, "stderr": stderr}


def run_owned(args, *, timeout=60, grace=5):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=grace)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=grace)
        raise ProofTimeout(process, timeout, stdout, stderr) from None
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
