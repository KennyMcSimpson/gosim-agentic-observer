"""Local entrypoint for the organizer's official v4 runner.

The vendored official transport uses select.select on subprocess pipes, which
only works for sockets on Windows. Keep the official engine files untouched
and supply a pipe-thread adapter at this local process boundary instead.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
from pathlib import Path


def _install_windows_pipe_transport() -> None:
    """Replace local pipe I/O on Windows without editing the official engine."""
    if os.name != "nt":
        return

    import project_platform.transport as transport_module

    BaseTransport = transport_module.JsonlTransport

    class WindowsPipeJsonlTransport(BaseTransport):
        def start(self) -> None:
            if self.process is not None:
                return
            self.process = transport_module.subprocess.Popen(
                self.command,
                cwd=self.cwd,
                env=self.environment,
                stdin=transport_module.subprocess.PIPE,
                stdout=transport_module.subprocess.PIPE,
                stderr=transport_module.subprocess.PIPE,
                bufsize=0,
                start_new_session=True,
            )
            self._stdout_lines: queue.Queue = queue.Queue()
            self._stdin_writes: queue.Queue = queue.Queue()
            self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
            self._stderr_thread = threading.Thread(
                target=self._drain_log, args=(self.process.stderr,), daemon=True
            )
            self._stdin_thread = threading.Thread(target=self._write_stdin, daemon=True)
            self._stdout_thread.start()
            self._stderr_thread.start()
            self._stdin_thread.start()

        def _read_stdout(self) -> None:
            try:
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        break
                    self._stdout_lines.put(line)
            except BaseException as error:
                self._stdout_lines.put(error)
            finally:
                self._stdout_lines.put(None)

        def _write_stdin(self) -> None:
            while True:
                item = self._stdin_writes.get()
                if item is None:
                    return
                data, completed, errors = item
                try:
                    stream = self.process.stdin
                    pending = memoryview(data)
                    while pending:
                        written = stream.write(pending)
                        if not written:
                            raise BrokenPipeError("agent stdin closed before the request was written")
                        pending = pending[written:]
                    stream.flush()
                except BaseException as error:
                    errors.append(error)
                finally:
                    completed.set()

        def send(self, message, deadline: float, *, limit: int = transport_module.MAX_REQUEST_BYTES) -> None:
            self.start()
            data = json.dumps(
                message, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode() + b"\n"
            if len(data) > limit:
                raise transport_module.ExecutionError("Public protocol request exceeds the size limit.")
            completed = threading.Event()
            errors = []
            self._stdin_writes.put((data, completed, errors))
            if not completed.wait(timeout=self._remaining(deadline)):
                self.close(force=True)
                raise transport_module.GlobalDeadlineExpired()
            if errors:
                error = errors[0]
                self.close(force=True)
                if isinstance(error, BrokenPipeError):
                    raise transport_module.ExecutionError("Project exited before reading a request.") from error
                raise transport_module.ExecutionError("Could not write a protocol request to the agent.") from error

        def receive(self, deadline: float) -> dict:
            self.start()
            try:
                item = self._stdout_lines.get(timeout=self._remaining(deadline))
            except queue.Empty:
                self.close(force=True)
                raise transport_module.GlobalDeadlineExpired()
            if item is None:
                raise transport_module.ExecutionError("Project exited without a complete response.")
            if isinstance(item, BaseException):
                raise transport_module.ExecutionError("Could not read a protocol response from the agent.") from item
            line = item.rstrip(b"\r\n")
            if len(line) > transport_module.MAX_RESPONSE_BYTES:
                raise transport_module.ExecutionError("Project response exceeds the size limit.")
            try:
                payload = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, UnicodeError) as error:
                raise transport_module.ExecutionError(
                    "Project stdout must contain JSON-Lines responses; send logs to stderr."
                ) from error
            if not isinstance(payload, dict):
                raise transport_module.ExecutionError("Project response must be a JSON object.")
            return payload

        def close(self, force: bool = False) -> None:
            process = self.process
            if process is None:
                return
            if process.poll() is None:
                try:
                    process.kill() if force else process.terminate()
                    process.wait(timeout=2)
                except transport_module.subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                except OSError:
                    pass
            try:
                self._stdin_writes.put_nowait(None)
            except (AttributeError, queue.Full):
                pass
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    stream.close()
                except OSError:
                    pass
            for name in ("_stdout_thread", "_stderr_thread", "_stdin_thread"):
                thread = getattr(self, name, None)
                if thread is not None:
                    thread.join(timeout=2)
            self.process = None

    transport_module.JsonlTransport = WindowsPipeJsonlTransport


def main() -> int:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    runner = root / "vendor" / "gosim-official-v4" / "runner"
    if not runner.is_dir():
        print("official v4 runner payload is missing: %s" % runner, file=sys.stderr)
        return 2
    sys.path.insert(0, str(runner))
    _install_windows_pipe_transport()
    import run_local

    return int(run_local.main())


if __name__ == "__main__":
    raise SystemExit(main())
