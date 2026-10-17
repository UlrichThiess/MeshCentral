"""Portable lifecycle integration tests. No macOS permissions, services or network."""
import importlib.util
import ctypes
import json
import os
from pathlib import Path
import select
import shutil
import signal
import socket
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


class StatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="zoomsoft-status-tests-")
        root = Path(cls.temporary.name)
        source = root / "status.c"
        source.write_text(r'''
#include <stdio.h>
#include "Verbindungsstatus.h"
int main(void) {
    char line[4096];
    while (fgets(line, sizeof(line), stdin)) {
        line[strcspn(line, "\r\n")] = 0;
        printf("%d\n", zs_verbindungsstatus(line));
    }
    return 0;
}
''')
        cls.parser = root / "status"
        compiler = shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("A C compiler is required")
        subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT),
                        str(source), "-o", str(cls.parser)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def classify(self, *lines):
        result = subprocess.run([str(self.parser)], input="\n".join(lines) + "\n",
                                text=True, capture_output=True, check=True)
        return [int(value) for value in result.stdout.splitlines()]

    def test_connection_without_optional_authentication_debug_line(self):
        self.assertEqual(self.classify("Connecting to: wss://assist.example.invalid/agent.ashx",
                                       "Connected.", "Core module loaded"), [1, 2, 0])
        self.assertEqual(self.classify("Connecting to: wss://assist.example.invalid/agent.ashxConnected."), [2])

    def test_reconnect_and_trust_errors_replace_connected_state(self):
        self.assertEqual(self.classify("Connected.", "Control Channel Disconnected [4]...",
                                       "AutoRetry Connect in 5 seconds", "Connected.",
                                       "Invalid server signature", "ZOOMSOFT:ERROR Bildschirmprozess beendet"),
                         [2, 1, 1, 2, 3, 3])

    def test_unrelated_lines_do_not_report_a_connection(self):
        self.assertEqual(self.classify("", "Not Connected.", "Authentication Complete...",
                                       "ZOOMSOFT:KVMREADY", "LISTENING ON DOMAIN SOCKET"), [0, 0, 0, 0, 0])


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
        # The extra socket argument enables the production KVM lifecycle with
        # a harmless fixture on Linux and macOS. No real user's socket is used.
        command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-DZOOMSOFT_TEST_KVM",
                   str(ROOT / "Sitzungswaechter.c"), "-o", str(cls.guardian)]
        if sys.platform.startswith("linux"):
            command.append("-lutil")
        subprocess.run(command, check=True, capture_output=True)
        cls.socket_error = None
        try:
            with socket.socket(socket.AF_UNIX):
                pass
        except OSError as error:
            cls.socket_error = str(error)
        cls.agent = cls.root / "Test Agent | Sitzung"
        cls.agent.write_text("#!" + sys.executable + "\n" + r'''
import json, os, signal, socket, subprocess, sys, time
from pathlib import Path
mode = Path('mode').read_text()
if sys.argv[1] == '-kvmagent':
    Path('kvm.pid').write_text(str(os.getpid()))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    if mode == 'kvm-fail':
        print('BIND ERROR on DOMAIN SOCKET', flush=True)
        sys.exit(7)
    if mode == 'kvm-wait':
        time.sleep(120)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(sys.argv[2])
    listener.listen(4)
    Path('kvm.ready').write_text(str(time.monotonic_ns()))
    # Split the message to exercise readiness across separate pipe reads.
    print('LISTENING ON DOMAIN ', end='', flush=True)
    time.sleep(0.03)
    print('SOCKET', flush=True)
    while True:
        connection, _ = listener.accept()
        connection.close()
signal.signal(signal.SIGINT, signal.SIG_IGN if mode == 'stubborn' else lambda *_: sys.exit(0))
child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); time.sleep(120)'])
Path('child.pid').write_text(str(child.pid))
Path('agent.pid').write_text(str(os.getpid()))
Path('args.json').write_text(json.dumps({'args':sys.argv[1:], 'uid':os.getuid(), 'cwd':os.getcwd(), 'pgrp':os.getpgrp(), 'started':time.monotonic_ns()}))
print('Connected.', flush=True)
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
        # Keep below macOS's 104-byte Unix socket path limit, even when the
        # surrounding TemporaryDirectory is under /var/folders/...
        self.sockets = tempfile.TemporaryDirectory(prefix="zs-kvm-", dir="/tmp")
        self.socket_path = Path(self.sockets.name) / "screen.sock"

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
        for name in ("agent.pid", "child.pid", "kvm.pid"):
            path = self.data / name
            if path.exists():
                pid = int(path.read_text())
                if running(pid):
                    os.kill(pid, signal.SIGKILL)
                    wait_until(lambda: not running(pid))
        self.sockets.cleanup()

    def spawn(self, mode="normal", screen=False):
        (self.data / "mode").write_text(mode)
        command = [str(self.guardian), str(os.getpid()), str(self.agent), str(self.data)]
        if screen:
            command.append(str(self.socket_path))
        process = subprocess.Popen(command,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.processes.append(process)
        return process

    def start(self, mode="normal", screen=False):
        if screen:
            self.require_socket()
        process = self.spawn(mode, screen)
        wait_until(lambda: (self.data / "args.json").exists() or process.poll() is not None)
        self.assertIsNone(process.poll(), "Guardian exited before starting agent")
        return process

    def require_socket(self):
        if self.socket_error:
            self.skipTest("Local Unix sockets are unavailable: " + self.socket_error)

    def assert_session_stopped(self):
        for name in ("agent.pid", "child.pid", "kvm.pid"):
            path = self.data / name
            if not path.exists():
                continue
            pid = int(path.read_text())
            wait_until(lambda: not running(pid))

    def test_connection_output_and_local_log_arrive_while_agent_is_running(self):
        process = self.start()
        output = b""
        deadline = time.monotonic() + 2
        while b"Connected." not in output and time.monotonic() < deadline:
            readable, _, _ = select.select([process.stdout], [], [], 0.1)
            if readable:
                output += os.read(process.stdout.fileno(), 4096)
        self.assertIn(b"Connected.", output)
        self.assertIsNone(process.poll())
        log = self.data / "sitzung.log"
        self.assertIn("Connected.", log.read_text())
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_screen_starts_before_agent_and_stops_with_session(self):
        process = self.start(screen=True)
        args = json.loads((self.data / "args.json").read_text())
        self.assertLess(int((self.data / "kvm.ready").read_text()), args["started"])
        self.assertTrue(self.socket_path.is_socket())
        process.stdin.close()
        self.assertEqual(process.wait(timeout=4), 0)
        self.assert_session_stopped()
        self.assertFalse(self.socket_path.exists())
        self.assertIn(b"ZOOMSOFT:KVMREADY", process.stdout.read())

    def test_screen_failure_prevents_starting_server_connection(self):
        process = self.spawn("kvm-fail", screen=True)
        # Keep the control pipe open: communicate() would cancel startup and
        # correctly turn this into a normal user-requested shutdown instead.
        process.wait(timeout=4)
        output = process.stdout.read()
        self.assertEqual(process.returncode, 71)
        self.assertIn(b"ZOOMSOFT:ERROR", output)
        self.assertFalse((self.data / "agent.pid").exists())
        self.assert_session_stopped()

    def test_closing_during_screen_startup_cleans_helper_without_connecting(self):
        process = self.spawn("kvm-wait", screen=True)
        wait_until(lambda: (self.data / "kvm.pid").exists())
        process.stdin.close()
        self.assertEqual(process.wait(timeout=4), 0)
        self.assertFalse((self.data / "agent.pid").exists())
        self.assert_session_stopped()

    def test_unexpected_screen_exit_also_stops_server_connection(self):
        process = self.start(screen=True)
        os.kill(int((self.data / "kvm.pid").read_text()), signal.SIGKILL)
        self.assertNotEqual(process.wait(timeout=4), 0)
        self.assert_session_stopped()
        self.assertIn(b"ZOOMSOFT:ERROR", process.stdout.read())
        self.assertFalse(self.socket_path.exists())

    def test_existing_listener_is_reused_and_remains_after_session(self):
        self.require_socket()
        listener = socket.socket(socket.AF_UNIX)
        self.addCleanup(listener.close)
        listener.bind(str(self.socket_path))
        listener.listen(4)
        process = self.start(screen=True)
        self.assertFalse((self.data / "kvm.pid").exists())
        process.stdin.close()
        self.assertEqual(process.wait(timeout=4), 0)
        self.assert_session_stopped()
        self.assertIn(b"ZOOMSOFT:KVMREUSED", process.stdout.read())
        self.assertTrue(self.socket_path.is_socket())
        with socket.socket(socket.AF_UNIX) as probe:
            probe.connect(str(self.socket_path))

    def test_stale_socket_is_replaced_and_cleaned_up(self):
        self.require_socket()
        with socket.socket(socket.AF_UNIX) as stale:
            stale.bind(str(self.socket_path))
        process = self.start(screen=True)
        self.assertTrue((self.data / "kvm.ready").exists())
        process.stdin.close()
        self.assertEqual(process.wait(timeout=4), 0)
        self.assert_session_stopped()
        self.assertFalse(self.socket_path.exists())

    def test_non_socket_path_is_preserved_and_prevents_connection(self):
        self.socket_path.write_text("unrelated file")
        process = self.spawn(screen=True)
        output, _ = process.communicate(timeout=4)
        self.assertEqual(process.returncode, 71)
        self.assertIn(b"ZOOMSOFT:ERROR", output)
        self.assertFalse((self.data / "agent.pid").exists())
        self.assertFalse((self.data / "kvm.pid").exists())
        self.assertEqual(self.socket_path.read_text(), "unrelated file")

    def test_socket_replaced_by_another_process_is_not_removed_on_stop(self):
        process = self.start(screen=True)
        self.socket_path.unlink()
        with socket.socket(socket.AF_UNIX) as replacement:
            replacement.bind(str(self.socket_path))
            replacement.listen(4)
            process.stdin.close()
            self.assertEqual(process.wait(timeout=4), 0)
            self.assert_session_stopped()
            self.assertTrue(self.socket_path.is_socket())

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
command = [sys.argv[1], str(os.getpid()), sys.argv[2], sys.argv[3]] + sys.argv[5:]
process = subprocess.Popen(command, stdin=int(sys.argv[4]), stdout=subprocess.DEVNULL)
Path(sys.argv[3], 'guardian.pid').write_text(str(process.pid))
while True: time.sleep(1)
'''
        command = [sys.executable, "-c", harness, str(self.guardian),
                   str(self.agent), str(self.data), str(readfd)]
        if not self.socket_error:
            command.append(str(self.socket_path))
        parent = subprocess.Popen(command, pass_fds=(readfd,))
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
