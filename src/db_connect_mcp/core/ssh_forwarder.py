"""Native Paramiko local port forwarding with bounded lifecycle management."""

from __future__ import annotations

import contextlib
import enum
import logging
import selectors
import socket
import socketserver
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast

import paramiko

from db_connect_mcp.models.config import SSHTunnelConfig

logger = logging.getLogger(__name__)

_RELAY_CHUNK_SIZE = 64 * 1024
_RELAY_BUFFER_LIMIT = 1024 * 1024
_RELAY_POLL_SECONDS = 0.25
_SHUTDOWN_TIMEOUT_SECONDS = 5.0


class SSHTunnelErrorCode(str, enum.Enum):
    """Stable classification for SSH tunnel failures."""

    UNKNOWN = "SSH_UNKNOWN_FAILED"
    CONNECT = "SSH_CONNECT_FAILED"
    HOST_KEY = "SSH_HOST_KEY_FAILED"
    AUTH = "SSH_AUTH_FAILED"
    CHANNEL = "SSH_CHANNEL_FAILED"
    LISTENER = "SSH_LISTENER_FAILED"
    RELAY = "SSH_RELAY_FAILED"


class SSHTunnelError(Exception):
    """A sanitized SSH tunnel failure with a machine-readable code."""

    def __init__(
        self,
        message: str,
        *,
        code: SSHTunnelErrorCode = SSHTunnelErrorCode.UNKNOWN,
    ) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")


class _AcceptHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Accept an unknown host key without persisting it."""

    def missing_host_key(
        self,
        client: paramiko.SSHClient,
        hostname: str,
        key: paramiko.PKey,
    ) -> None:
        del client, hostname, key


@dataclass(eq=False)
class _TransportGeneration:
    """An SSH client retained while forwarding channels still lease it."""

    client: paramiko.SSHClient
    transport: paramiko.Transport
    leases: int = 0
    retired: bool = False


class _ChannelLease:
    """Release a transport-generation lease when its channel is closed."""

    def __init__(
        self,
        owner: ParamikoTunnelForwarder,
        generation: _TransportGeneration,
        channel: paramiko.Channel,
    ) -> None:
        self._owner = owner
        self._generation = generation
        self.channel = channel
        self._closed = False

    def close(self) -> None:
        """Close the channel and release its transport generation once."""
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            self.channel.close()
        self._owner._release_generation(self._generation)


@dataclass
class _ActiveSession:
    """Resources owned by one local forwarding handler."""

    thread: threading.Thread
    local_socket: socket.socket
    channel: paramiko.Channel | None = None


class _ForwardingServer(socketserver.ThreadingTCPServer):
    """Thread-per-connection local listener owned by a forwarder."""

    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False
    request_queue_size = 128

    def __init__(
        self,
        server_address: tuple[str, int],
        forwarder: ParamikoTunnelForwarder,
        address_family: socket.AddressFamily,
    ) -> None:
        self.address_family = address_family
        self.forwarder = forwarder
        super().__init__(server_address, _ForwardingHandler)


class _ForwardingHandler(socketserver.BaseRequestHandler):
    """Delegate a local connection to its owning forwarder."""

    def handle(self) -> None:
        server = cast(_ForwardingServer, self.server)
        local_socket = cast(socket.socket, self.request)
        server.forwarder._handle_connection(local_socket, self.client_address)


ClientFactory = Callable[[], paramiko.SSHClient]


class ParamikoTunnelForwarder:
    """Forward a stable local listener through replaceable Paramiko clients."""

    def __init__(
        self,
        config: SSHTunnelConfig,
        *,
        password: str | None = None,
        pkey: paramiko.PKey | None = None,
        client_factory: ClientFactory = paramiko.SSHClient,
    ) -> None:
        self.config = config
        self._password = password
        self._pkey = pkey
        self._client_factory = client_factory

        self._lifecycle_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._reconnect_lock = threading.Lock()
        self._sessions_lock = threading.Lock()
        self._closing = threading.Event()
        self._listener_ready = threading.Event()

        self._current_generation: _TransportGeneration | None = None
        self._retired_generations: set[_TransportGeneration] = set()
        self._server: _ForwardingServer | None = None
        self._server_thread: threading.Thread | None = None
        self._local_bind_port: int | None = None
        self._sessions: dict[int, _ActiveSession] = {}
        self._warned_insecure_host_key = False

    @property
    def local_bind_port(self) -> int | None:
        """Return the stable listener port after startup."""
        return self._local_bind_port

    @property
    def is_active(self) -> bool:
        """Return whether the listener and authenticated SSH transport are active."""
        with self._state_lock:
            generation = self._current_generation
            server = self._server
            server_thread = self._server_thread
            return bool(
                not self._closing.is_set()
                and generation is not None
                and self._generation_is_active(generation)
                and server is not None
                and server.fileno() >= 0
                and server_thread is not None
                and server_thread.is_alive()
            )

    def start(self) -> int:
        """Connect, preflight the target, and publish the local listener."""
        with self._lifecycle_lock:
            if self.is_active:
                if self._local_bind_port is None:
                    raise SSHTunnelError(
                        "Tunnel is active but its listener port is unavailable",
                        code=SSHTunnelErrorCode.LISTENER,
                    )
                return self._local_bind_port

            self._closing.clear()
            self._listener_ready.clear()
            generation = self._connect_generation()

            try:
                server = self._create_server()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    generation.client.close()
                if isinstance(exc, SSHTunnelError):
                    raise
                raise SSHTunnelError(
                    "Could not bind the local SSH forwarding listener",
                    code=SSHTunnelErrorCode.LISTENER,
                ) from exc

            with self._state_lock:
                self._current_generation = generation
                self._server = server
                self._local_bind_port = int(server.server_address[1])
                thread = threading.Thread(
                    target=self._serve,
                    name="db-connect-ssh-listener",
                    daemon=True,
                )
                self._server_thread = thread
                thread.start()

            readiness_timeout = float(self.config.connect_timeout or 10)
            if not self._listener_ready.wait(readiness_timeout):
                self.stop()
                raise SSHTunnelError(
                    "The local SSH forwarding listener did not become ready",
                    code=SSHTunnelErrorCode.LISTENER,
                )

            if self._local_bind_port is None:
                self.stop()
                raise SSHTunnelError(
                    "The local SSH forwarding listener has no bound port",
                    code=SSHTunnelErrorCode.LISTENER,
                )
            return self._local_bind_port

    def stop(self) -> None:
        """Stop accepting connections and close all SSH and relay resources."""
        with self._lifecycle_lock:
            self._closing.set()
            with self._state_lock:
                server = self._server
                server_thread = self._server_thread

            if server is not None:
                if server_thread is not None and server_thread.is_alive():
                    with contextlib.suppress(Exception):
                        server.shutdown()
                with contextlib.suppress(Exception):
                    server.server_close()

            if (
                server_thread is not None
                and server_thread is not threading.current_thread()
            ):
                server_thread.join(_SHUTDOWN_TIMEOUT_SECONDS)

            with self._sessions_lock:
                sessions = list(self._sessions.values())
            for session in sessions:
                self._close_socket(session.local_socket)
                if session.channel is not None:
                    with contextlib.suppress(Exception):
                        session.channel.close()

            # Serialize the generation snapshot with reconnect. A reconnect that
            # was already dialing when shutdown began must be included here and
            # closed instead of publishing a client after stop() returns.
            with self._reconnect_lock:
                with self._state_lock:
                    generations = list(self._retired_generations)
                    if self._current_generation is not None:
                        generations.append(self._current_generation)
                    self._current_generation = None
                    self._retired_generations.clear()
                for generation in generations:
                    with contextlib.suppress(Exception):
                        generation.client.close()

            deadline = time.monotonic() + _SHUTDOWN_TIMEOUT_SECONDS
            for session in sessions:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if session.thread is not threading.current_thread():
                    session.thread.join(remaining)

            with self._state_lock:
                self._server = None
                self._server_thread = None
                self._local_bind_port = None
            self._listener_ready.clear()

    def ensure_active(self) -> bool:
        """Verify target-channel health and recover the SSH transport once."""
        if self._server is None:
            self.start()
            return True
        if not self._listener_is_active():
            raise SSHTunnelError(
                "The stable local SSH forwarding listener is no longer running",
                code=SSHTunnelErrorCode.LISTENER,
            )

        lease = self._acquire_channel((self.config.local_host, 0))
        lease.close()
        return True

    def _serve(self) -> None:
        """Run the local listener until shutdown is requested."""
        server = self._server
        if server is None:
            return
        self._listener_ready.set()
        try:
            server.serve_forever(poll_interval=0.1)
        except Exception:
            if not self._closing.is_set():
                logger.exception("SSH_LISTENER_FAILED: listener thread exited")

    def _create_server(self) -> _ForwardingServer:
        address_family = (
            socket.AF_INET6 if ":" in self.config.local_host else socket.AF_INET
        )
        return _ForwardingServer(
            (self.config.local_host, self.config.local_port or 0),
            self,
            address_family,
        )

    def _listener_is_active(self) -> bool:
        with self._state_lock:
            return bool(
                not self._closing.is_set()
                and self._server is not None
                and self._server.fileno() >= 0
                and self._server_thread is not None
                and self._server_thread.is_alive()
            )

    def _connect_generation(self) -> _TransportGeneration:
        client = self._client_factory()
        try:
            self._configure_host_keys(client)
            client.connect(
                hostname=self.config.ssh_host,
                port=self.config.ssh_port,
                username=self.config.ssh_username,
                password=self._password,
                pkey=self._pkey,
                timeout=self.config.connect_timeout,
                banner_timeout=self.config.banner_timeout,
                auth_timeout=self.config.auth_timeout,
                channel_timeout=self.config.channel_timeout,
                look_for_keys=False,
                allow_agent=False,
            )
            transport = client.get_transport()
            if (
                transport is None
                or not transport.is_active()
                or not transport.is_authenticated()
            ):
                raise SSHTunnelError(
                    "The bastion did not provide an authenticated SSH transport",
                    code=SSHTunnelErrorCode.AUTH,
                )
            transport.set_keepalive(self.config.keepalive_interval)
            generation = _TransportGeneration(client=client, transport=transport)
            if self.config.target_preflight:
                self._preflight_generation(generation)
            return generation
        except paramiko.BadHostKeyException as exc:
            with contextlib.suppress(Exception):
                client.close()
            raise SSHTunnelError(
                "Bastion host-key verification failed",
                code=SSHTunnelErrorCode.HOST_KEY,
            ) from exc
        except paramiko.AuthenticationException as exc:
            with contextlib.suppress(Exception):
                client.close()
            raise SSHTunnelError(
                "Bastion authentication failed",
                code=SSHTunnelErrorCode.AUTH,
            ) from exc
        except SSHTunnelError:
            with contextlib.suppress(Exception):
                client.close()
            raise
        except (OSError, EOFError, paramiko.SSHException) as exc:
            with contextlib.suppress(Exception):
                client.close()
            raise SSHTunnelError(
                "Could not establish the SSH connection to the bastion",
                code=SSHTunnelErrorCode.CONNECT,
            ) from exc

    def _configure_host_keys(self, client: paramiko.SSHClient) -> None:
        if not self.config.strict_host_key:
            if not self._warned_insecure_host_key:
                logger.warning(
                    "SSH host-key verification is disabled; enable "
                    "SSH_STRICT_HOST_KEY for production verification"
                )
                self._warned_insecure_host_key = True
            client.set_missing_host_key_policy(_AcceptHostKeyPolicy())
            return

        try:
            client.load_system_host_keys()
            if self.config.known_hosts_path:
                path = Path(self.config.known_hosts_path).expanduser()
                client.load_system_host_keys(str(path))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        except OSError as exc:
            raise SSHTunnelError(
                "The configured SSH known-hosts file could not be loaded",
                code=SSHTunnelErrorCode.HOST_KEY,
            ) from exc

    def _preflight_generation(self, generation: _TransportGeneration) -> None:
        channel: paramiko.Channel | None = None
        try:
            channel = generation.transport.open_channel(
                "direct-tcpip",
                dest_addr=self._remote_address,
                src_addr=(self.config.local_host, 0),
                timeout=self.config.channel_timeout,
            )
            if channel is None:
                raise paramiko.SSHException("SSH server returned no channel")
        except Exception as exc:
            raise SSHTunnelError(
                "Bastion authentication succeeded, but the database target channel "
                "could not be opened",
                code=SSHTunnelErrorCode.CHANNEL,
            ) from exc
        finally:
            if channel is not None:
                with contextlib.suppress(Exception):
                    channel.close()

    @property
    def _remote_address(self) -> tuple[str, int]:
        return (
            self.config.remote_host or "127.0.0.1",
            self.config.remote_port or 5432,
        )

    @staticmethod
    def _generation_is_active(generation: _TransportGeneration) -> bool:
        return bool(
            generation.transport.is_active() and generation.transport.is_authenticated()
        )

    def _reserve_current_generation(self) -> _TransportGeneration | None:
        with self._state_lock:
            generation = self._current_generation
            if generation is None or not self._generation_is_active(generation):
                return None
            generation.leases += 1
            return generation

    def _release_generation(self, generation: _TransportGeneration) -> None:
        close_client = False
        with self._state_lock:
            generation.leases = max(0, generation.leases - 1)
            if generation.retired and generation.leases == 0:
                self._retired_generations.discard(generation)
                close_client = True
        if close_client:
            with contextlib.suppress(Exception):
                generation.client.close()

    def _replace_generation(
        self,
        expected: _TransportGeneration | None,
    ) -> None:
        with self._reconnect_lock:
            if self._closing.is_set():
                raise SSHTunnelError(
                    "SSH tunnel shutdown is in progress",
                    code=SSHTunnelErrorCode.CONNECT,
                )

            with self._state_lock:
                current = self._current_generation
                if current is not expected and current is not None:
                    if self._generation_is_active(current):
                        return
                if expected is None and current is not None:
                    if self._generation_is_active(current):
                        return

            replacement = self._connect_generation()
            close_previous = False
            previous: _TransportGeneration | None
            with self._state_lock:
                previous = self._current_generation
                self._current_generation = replacement
                if previous is not None:
                    previous.retired = True
                    if previous.leases == 0:
                        close_previous = True
                    else:
                        self._retired_generations.add(previous)
            if close_previous and previous is not None:
                with contextlib.suppress(Exception):
                    previous.client.close()

    def _open_channel_once(
        self,
        source_address: tuple[str, int],
    ) -> tuple[_TransportGeneration, paramiko.Channel]:
        generation = self._reserve_current_generation()
        if generation is None:
            self._replace_generation(None)
            generation = self._reserve_current_generation()
        if generation is None:
            raise paramiko.SSHException("No active SSH transport")

        try:
            channel = generation.transport.open_channel(
                "direct-tcpip",
                dest_addr=self._remote_address,
                src_addr=source_address,
                timeout=self.config.channel_timeout,
            )
            if channel is None:
                raise paramiko.SSHException("SSH server returned no channel")
            return generation, channel
        except Exception:
            self._release_generation(generation)
            raise

    def _acquire_channel(self, source_address: tuple[str, int]) -> _ChannelLease:
        first_generation: _TransportGeneration | None = None
        try:
            first_generation, channel = self._open_channel_once(source_address)
            return _ChannelLease(self, first_generation, channel)
        except paramiko.ChannelException as exc:
            raise self._channel_error() from exc
        except SSHTunnelError:
            raise
        except (OSError, EOFError, paramiko.SSHException):
            with self._state_lock:
                expected = first_generation or self._current_generation
            try:
                self._replace_generation(expected)
                generation, channel = self._open_channel_once(source_address)
                return _ChannelLease(self, generation, channel)
            except SSHTunnelError:
                raise
            except Exception as retry_error:
                raise self._channel_error() from retry_error

    @staticmethod
    def _channel_error() -> SSHTunnelError:
        return SSHTunnelError(
            "The bastion could not open a channel to the configured database target",
            code=SSHTunnelErrorCode.CHANNEL,
        )

    def _handle_connection(
        self,
        local_socket: socket.socket,
        client_address: tuple[object, ...],
    ) -> None:
        thread = threading.current_thread()
        session = _ActiveSession(thread=thread, local_socket=local_socket)
        session_key = id(session)
        with self._sessions_lock:
            self._sessions[session_key] = session

        lease: _ChannelLease | None = None
        try:
            source_host = client_address[0]
            source_port = client_address[1]
            if not isinstance(source_host, str) or not isinstance(source_port, int):
                raise SSHTunnelError(
                    "The local forwarding client address is invalid",
                    code=SSHTunnelErrorCode.RELAY,
                )
            source_address = (source_host, source_port)
            lease = self._acquire_channel(source_address)
            session.channel = lease.channel
            self._relay(local_socket, lease.channel)
        except SSHTunnelError as exc:
            logger.warning("%s: local forwarding connection closed", exc.code.value)
        except Exception:
            if not self._closing.is_set():
                logger.exception("SSH_RELAY_FAILED: local forwarding connection closed")
        finally:
            self._close_socket(local_socket)
            if lease is not None:
                lease.close()
            with self._sessions_lock:
                self._sessions.pop(session_key, None)

    def _relay(
        self,
        local_socket: socket.socket,
        channel: paramiko.Channel,
    ) -> None:
        local_socket.setblocking(False)
        channel.setblocking(False)
        local_to_channel = bytearray()
        channel_to_local = bytearray()
        local_read_open = True
        local_write_open = True
        channel_read_open = True
        channel_write_open = True

        with selectors.DefaultSelector() as selector:
            while not self._closing.is_set():
                if local_to_channel and channel_write_open and channel.send_ready():
                    try:
                        sent = channel.send(local_to_channel)
                    except (BlockingIOError, socket.timeout):
                        sent = 0
                    if sent > 0:
                        del local_to_channel[:sent]
                    elif sent == 0 and channel.closed:
                        channel_write_open = False
                        local_read_open = False
                        local_to_channel.clear()

                if not local_read_open and not local_to_channel and channel_write_open:
                    with contextlib.suppress(Exception):
                        channel.shutdown_write()
                    channel_write_open = False

                if not channel_read_open and not channel_to_local and local_write_open:
                    with contextlib.suppress(OSError):
                        local_socket.shutdown(socket.SHUT_WR)
                    local_write_open = False

                local_events = 0
                if local_read_open and len(local_to_channel) < _RELAY_BUFFER_LIMIT:
                    local_events |= selectors.EVENT_READ
                if local_write_open and channel_to_local:
                    local_events |= selectors.EVENT_WRITE

                channel_events = 0
                if channel_read_open and len(channel_to_local) < _RELAY_BUFFER_LIMIT:
                    channel_events |= selectors.EVENT_READ

                self._sync_registration(selector, local_socket, local_events, "local")
                self._sync_registration(selector, channel, channel_events, "channel")

                if (
                    not local_read_open
                    and not channel_read_open
                    and not local_to_channel
                    and not channel_to_local
                ):
                    return
                if local_events == 0 and channel_events == 0 and not local_to_channel:
                    return

                try:
                    events = selector.select(_RELAY_POLL_SECONDS)
                except (OSError, ValueError):
                    if self._closing.is_set():
                        return
                    raise

                for key, mask in events:
                    if key.data == "local":
                        if mask & selectors.EVENT_READ:
                            capacity = _RELAY_BUFFER_LIMIT - len(local_to_channel)
                            try:
                                data = local_socket.recv(
                                    min(_RELAY_CHUNK_SIZE, capacity)
                                )
                            except BlockingIOError:
                                data = None
                            if data:
                                local_to_channel.extend(data)
                            elif data == b"":
                                local_read_open = False
                        if mask & selectors.EVENT_WRITE and channel_to_local:
                            try:
                                sent = local_socket.send(channel_to_local)
                            except BlockingIOError:
                                sent = 0
                            if sent > 0:
                                del channel_to_local[:sent]
                            elif sent == 0:
                                local_write_open = False
                                channel_read_open = False
                                channel_to_local.clear()
                                with contextlib.suppress(Exception):
                                    channel.shutdown_read()
                    elif mask & selectors.EVENT_READ:
                        capacity = _RELAY_BUFFER_LIMIT - len(channel_to_local)
                        try:
                            data = channel.recv(min(_RELAY_CHUNK_SIZE, capacity))
                        except (BlockingIOError, socket.timeout):
                            data = None
                        if data:
                            channel_to_local.extend(data)
                        elif data == b"":
                            channel_read_open = False

    @staticmethod
    def _sync_registration(
        selector: selectors.BaseSelector,
        fileobj: socket.socket | paramiko.Channel,
        events: int,
        data: str,
    ) -> None:
        try:
            selector.get_key(fileobj)
        except KeyError:
            if events:
                selector.register(fileobj, events, data)
        else:
            if events:
                selector.modify(fileobj, events, data)
            else:
                selector.unregister(fileobj)

    @staticmethod
    def _close_socket(sock: socket.socket) -> None:
        with contextlib.suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            sock.close()
