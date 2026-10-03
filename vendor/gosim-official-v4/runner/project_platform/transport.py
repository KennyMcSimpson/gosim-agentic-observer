"""Bounded JSON-Lines transport. Isolation is supplied by the Docker launcher."""
from __future__ import annotations

import json
import os
import select
import subprocess
import threading
import time
from pathlib import Path
from typing import Mapping

from challenge.challenge_workflow import GlobalDeadlineExpired
from challenge.contracts import PARTICIPANT_PROTOCOL_VERSION

MAX_RESPONSE_BYTES = 512 * 1024
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_INITIALIZATION_BYTES = 128 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024
# The participant's own stderr, kept for the private result download as agent.log.
AGENT_LOG_BYTES = 2 * 1024 * 1024
# Graceful shutdown allowance after the final "finish" message: the score is
# already fixed, so these seconds never count against the scenario clock.
FINISH_GRACE_SECONDS = 30

NORMAL_TERMINATION_REASONS = ("survey_complete", "global_wallclock_expired")
# v4 ends normally in these as well; the v4 engine sends "finish" after every run.
V4_TERMINATION_REASONS = ("survey_complete", "agent_finished", "global_wallclock_expired", "agent_error")


class ExecutionError(RuntimeError):
    pass


class JsonlTransport:
    """Run a persistent command and exchange only public protocol messages.

    This class alone is NOT a sandbox. Production callers must supply a command
    from DockerWorkspace, on a machine without hidden scenarios or admin keys.
    """

    def __init__(self, command: list[str], *, cwd: Path | None = None,
                 environment: Mapping[str, str] | None = None,
                 redactions: tuple[str, ...] = (), initialization_seconds: float = 30,
                 log_limit: int = MAX_LOG_BYTES):
        # The envelope version of every engine message. The v4 engine switches it to
        # participant-agent-protocol-v4 before the first message; v3 keeps the default.
        self.protocol_version = PARTICIPANT_PROTOCOL_VERSION
        self.command = command
        self.cwd = cwd
        self.environment = dict(environment) if environment is not None else None
        self.initialization_seconds = initialization_seconds
        self.redactions = tuple(value for value in redactions if value)
        self.log_limit = log_limit
        self.log_truncated = False
        self.process: subprocess.Popen | None = None
        self._buffer = bytearray()
        self._log = bytearray()
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None

    def start(self) -> None:
        if self.process is not None:
            return
        self.process = subprocess.Popen(
            self.command, cwd=self.cwd, env=self.environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, start_new_session=True,
        )
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)
        self._reader = threading.Thread(target=self._drain_log, args=(self.process.stderr,), daemon=True)
        self._reader.start()

    def _drain_log(self, stream) -> None:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            with self._lock:
                self._log.extend(chunk)
                # Trim with slack, so a chatty project costs amortized O(1) per byte.
                if len(self._log) > 2 * self.log_limit:
                    del self._log[:-self.log_limit]
                    self.log_truncated = True

    @property
    def log(self) -> str:
        with self._lock:
            if len(self._log) > self.log_limit:
                self.log_truncated = True
            text = bytes(self._log[-self.log_limit:]).decode(errors="replace")
        for secret in self.redactions:
            text = text.replace(secret, "[REDACTED]")
        return text

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            self.close(force=True)
            raise GlobalDeadlineExpired()
        return remaining

    def send(self, message: Mapping, deadline: float, *, limit: int = MAX_REQUEST_BYTES) -> None:
        self.start()
        data = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode() + b"\n"
        if len(data) > limit:
            raise ExecutionError("Public protocol request exceeds the size limit.")
        pending = memoryview(data)
        stream = self.process.stdin
        while pending:
            if not select.select([], [stream], [], self._remaining(deadline))[1]:
                self.close(force=True)
                raise GlobalDeadlineExpired()
            try:
                count = os.write(stream.fileno(), pending)
            except BlockingIOError:
                continue
            except BrokenPipeError as exc:
                raise ExecutionError("Project exited before reading a request.") from exc
            pending = pending[count:]

    def receive(self, deadline: float) -> dict:
        self.start()
        stream = self.process.stdout
        while b"\n" not in self._buffer:
            if len(self._buffer) > MAX_RESPONSE_BYTES:
                raise ExecutionError("Project response exceeds the size limit.")
            if not select.select([stream], [], [], self._remaining(deadline))[0]:
                self.close(force=True)
                raise GlobalDeadlineExpired()
            try:
                chunk = os.read(stream.fileno(), 65536)
            except BlockingIOError:
                continue
            if not chunk:
                raise ExecutionError("Project exited without a complete response.")
            self._buffer.extend(chunk)
        line, rest = self._buffer.split(b"\n", 1)
        self._buffer = bytearray(rest)
        if len(line) > MAX_RESPONSE_BYTES:
            raise ExecutionError("Project response exceeds the size limit.")
        try:
            payload = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError) as exc:
            raise ExecutionError("Project stdout must contain JSON-Lines responses; send logs to stderr.") from exc
        if not isinstance(payload, dict):
            raise ExecutionError("Project response must be a JSON object.")
        return payload

    def publish_initial(self, publication: Mapping) -> None:
        self.send({"protocol_version": self.protocol_version,
                   "message_type": "initialize", "payload": publication},
                  time.monotonic() + self.initialization_seconds, limit=MAX_INITIALIZATION_BYTES)

    def finish(self, termination_reason: str, last_decision_sequence: int, *,
               grace_seconds: float = FINISH_GRACE_SECONDS, extra: Mapping | None = None) -> None:
        """End a normally finished run gracefully: one final "finish" line,
        then stdin EOF, then up to grace_seconds for the process to exit on its
        own before the usual terminate/kill. Best-effort and never raises: a
        project that crashes on the message, ignores it or hangs must not turn
        an already-scored run into a failure. Anything printed to stdout after
        the message is ignored; stderr keeps flowing into the log."""
        process = self.process
        if process is None:
            return
        grace_deadline = time.monotonic() + grace_seconds
        if process.poll() is None:
            try:
                self.send({"protocol_version": self.protocol_version,
                           "message_type": "finish",
                           "payload": {**(extra or {}),
                                       "termination_reason": termination_reason,
                                       "last_decision_sequence": int(last_decision_sequence),
                                       "grace_seconds": grace_seconds}}, grace_deadline)
            except (ExecutionError, GlobalDeadlineExpired):
                pass  # an unreadable or full pipe is handled by the kill below
        if self.process is None:
            return  # a failed send already force-closed the process
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=max(0.0, grace_deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
        self.close()

    def __call__(self, snapshot: Mapping, deadline_monotonic: float) -> dict:
        sequence = snapshot["decision_sequence"]
        self.send({"protocol_version": self.protocol_version,
                   "message_type": "decision_request", "decision_sequence": sequence,
                   "payload": snapshot}, deadline_monotonic)
        response = self.receive(deadline_monotonic)
        if (response.get("protocol_version") != self.protocol_version or
                response.get("message_type") != "decision_response" or
                type(response.get("decision_sequence")) is not int or
                response["decision_sequence"] != sequence):
            raise ExecutionError("Project response does not match the current protocol request.")
        return response

    def close(self, force: bool = False) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            process.kill() if force else process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        for stream in (process.stdin, process.stdout):
            stream.close()
        if self._reader:
            self._reader.join(timeout=2)
        process.stderr.close()
        self.process = None
