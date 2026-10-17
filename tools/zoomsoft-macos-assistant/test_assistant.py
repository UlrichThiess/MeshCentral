"""Portable lifecycle integration tests. No macOS permissions, services or network."""
import importlib.util
import ctypes
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("assistant_build", ROOT / "erstellen.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def wait_until(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for fixture lifecycle")


def running(pid):
    try:
        info = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if info and info.si_pid == pid:
            os.waitpid(pid, os.WNOHANG)
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class SettingsTests(unittest.TestCase):
    source = "MeshName=Test\nMeshType=2\nMeshID=0x1234\nServerID=ABCDEF\nMeshServer=wss://assist.example.invalid/agent.ashx\n"

    def test_preserves_trust_and_overrides_service_update_policy(self):
        source = self.source + "disableUpdate=0\nforceUpdate=1\nAgentCapabilities=0\nStartupType=1\nnoUpdateCoreModule=1\n"
        result = build.connection_settings(source)
        values = dict(line.split("=", 1) for line in result.splitlines())
        self.assertEqual(values["ServerID"], "ABCDEF")
        self.assertEqual(values["MeshID"], "0x1234")
        self.assertEqual(values["disableUpdate"], "1")
        self.assertEqual(values["controlChannelDebug"], "1")
        self.assertNotIn("StartupType", values)
        self.assertNotIn("forceUpdate", values)
        self.assertNotIn("AgentCapabilities", values)
        self.assertNotIn("noUpdateCoreModule", values)

    def test_rejects_missing_ambiguous_or_insecure_connection(self):
        for source in [self.source.replace("ServerID=ABCDEF\n", ""),
                       self.source + "MeshServer=wss://other.invalid/agent.ashx\n",
                       self.source.replace("wss://", "ws://"),
                       self.source.replace("wss://", "wss://name:password@"),
                       self.source.replace("MeshType=2", "MeshType=1")]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                build.connection_settings(source)


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Adopt and reap fixture grandchildren on Linux, including PID namespaces
        # whose /proc mount does not expose this namespace's numeric PIDs.
        if sys.platform.startswith("linux"):
            if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
                raise OSError(ctypes.get_errno(), "Cannot adopt fixture descendants")
        cls.temporary = tempfile.TemporaryDirectory(prefix="zoomsoft-assistant-tests-")
        cls.root = Path(cls.temporary.name)
        cls.guardian = cls.root / "Sitzungswaechter"
        compiler = shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("A C compiler is required")
        command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                   str(ROOT / "Sitzungswaechter.c"), "-o", str(cls.guardian)]
        if sys.platform.startswith("linux"):
            command.append("-lutil")
        subprocess.run(command, check=True, capture_output=True)
        cls.agent = cls.root / "Test Agent | Sitzung"
        cls.agent.write_text("#!" + sys.executable + "\n" + r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
mode = Path('mode').read_text()
signal.signal(signal.SIGINT, signal.SIG_IGN if mode == 'stubborn' else lambda *_: sys.exit(0))
child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); time.sleep(120)'])
Path('child.pid').write_text(str(child.pid))
Path('agent.pid').write_text(str(os.getpid()))
Path('args.json').write_text(json.dumps({'args':sys.argv[1:], 'uid':os.getuid(), 'cwd':os.getcwd(), 'pgrp':os.getpgrp()}))
print('Authentication Complete...', flush=True)
if mode == 'exit': sys.exit(7)
while True: time.sleep(1)
''', encoding="utf-8")
        cls.agent.chmod(0o755)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="Daten | ü ", dir=self.root))
        (self.data / "mode").write_text("normal")
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()
        for name in ("agent.pid", "child.pid"):
            path = self.data / name
            if path.exists():
                pid = int(path.read_text())
                if running(pid):
                    os.kill(pid, signal.SIGKILL)

    def start(self, mode="normal"):
        (self.data / "mode").write_text(mode)
        process = subprocess.Popen([str(self.guardian), str(os.getpid()), str(self.agent), str(self.data)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.processes.append(process)
        wait_until(lambda: (self.data / "args.json").exists() or process.poll() is not None)
        self.assertIsNone(process.poll(), "Guardian exited before starting agent")
        return process

    def assert_session_stopped(self):
        for name in ("agent.pid", "child.pid"):
            pid = int((self.data / name).read_text())
            wait_until(lambda: not running(pid))

    def test_pipe_close_stops_agent_and_descendant_with_correct_context(self):
        process = self.start()
        args = json.loads((self.data / "args.json").read_text())
        self.assertEqual(args["uid"], os.getuid())
        self.assertEqual(args["cwd"], str(self.data))
        self.assertEqual(args["pgrp"], int((self.data / "agent.pid").read_text()))
        self.assertEqual(args["args"][0], "connect")
        self.assertIn("--disableUpdate=1", args["args"])
        process.stdin.close()
        self.assertEqual(process.wait(timeout=4), 0)
        self.assert_session_stopped()
        self.assertIn(b"Authentication Complete...", process.stdout.read())

    def test_stubborn_agent_is_killed_within_deadline(self):
        process = self.start("stubborn")
        started = time.monotonic()
        process.stdin.close()
        self.assertEqual(process.wait(timeout=4), 0)
        self.assertLess(time.monotonic() - started, 3)
        self.assert_session_stopped()

    def test_guardian_termination_also_cleans_session(self):
        process = self.start()
        process.terminate()
        self.assertEqual(process.wait(timeout=4), 0)
        self.assert_session_stopped()

    def test_unrelated_process_is_not_terminated(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        self.processes.append(unrelated)
        process = self.start()
        process.stdin.close()
        self.assertEqual(process.wait(timeout=4), 0)
        self.assert_session_stopped()
        self.assertIsNone(unrelated.poll())

    def test_inherited_ignored_sigchld_does_not_break_cleanup(self):
        process = subprocess.Popen([str(self.guardian), str(os.getpid()), str(self.agent), str(self.data)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   preexec_fn=lambda: signal.signal(signal.SIGCHLD, signal.SIG_IGN))
        self.processes.append(process)
        wait_until(lambda: (self.data / "args.json").exists())
        process.stdin.close()
        self.assertEqual(process.wait(timeout=4), 0)
        self.assert_session_stopped()

    def test_agent_exit_cleans_leftover_child(self):
        (self.data / "mode").write_text("exit")
        process = subprocess.Popen([str(self.guardian), str(os.getpid()), str(self.agent), str(self.data)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.processes.append(process)
        self.assertEqual(process.wait(timeout=4), 7)
        self.assert_session_stopped()

    def test_second_instance_cannot_take_over_active_session(self):
        first = self.start()
        second = subprocess.Popen([str(self.guardian), str(os.getpid()), str(self.agent), str(self.data)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.processes.append(second)
        output, _ = second.communicate(timeout=4)
        self.assertEqual(second.returncode, 73)
        self.assertIn(b"ZOOMSOFT:ERROR", output)
        self.assertIsNone(first.poll())
        self.assertTrue(running(int((self.data / "agent.pid").read_text())))
        first.stdin.close()
        self.assertEqual(first.wait(timeout=4), 0)
        self.assert_session_stopped()

    def test_parent_killed_even_with_control_pipe_kept_open(self):
        readfd, writefd = os.pipe()
        self.addCleanup(os.close, writefd)
        harness = r'''
import os, subprocess, sys, time
from pathlib import Path
process = subprocess.Popen([sys.argv[1], str(os.getpid()), sys.argv[2], sys.argv[3]], stdin=int(sys.argv[4]), stdout=subprocess.DEVNULL)
Path(sys.argv[3], 'guardian.pid').write_text(str(process.pid))
while True: time.sleep(1)
'''
        parent = subprocess.Popen([sys.executable, "-c", harness, str(self.guardian),
                                   str(self.agent), str(self.data), str(readfd)], pass_fds=(readfd,))
        self.processes.append(parent)
        os.close(readfd)
        wait_until(lambda: (self.data / "args.json").exists())
        parent.kill()
        parent.wait(timeout=3)
        self.assert_session_stopped()
        pid = int((self.data / "guardian.pid").read_text())
        wait_until(lambda: not running(pid))


if __name__ == "__main__":
    unittest.main(verbosity=2)
