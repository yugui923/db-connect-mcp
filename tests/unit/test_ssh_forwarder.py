"""Unit tests for the native Paramiko SSH forwarding layer."""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import paramiko
import pytest

from db_connect_mcp.core.ssh_forwarder import (
    ParamikoTunnelForwarder,
    SSHTunnelError,
    SSHTunnelErrorCode,
)
from db_connect_mcp.models.config import SSHTunnelConfig


def _config(**overrides: Any) -> SSHTunnelConfig:
    values: dict[str, Any] = {
        "ssh_host": "bastion.example.com",
        "ssh_username": "user",
        "ssh_password": "secret",
        "remote_host": "database.internal",
        "remote_port": 5432,
    }
    values.update(overrides)
    return SSHTunnelConfig(**values)


def _client_and_transport() -> tuple[MagicMock, MagicMock]:
    client = MagicMock(spec=paramiko.SSHClient)
    transport = MagicMock(spec=paramiko.Transport)
    transport.is_active.return_value = True
    transport.is_authenticated.return_value = True
    transport.open_channel.return_value = MagicMock(spec=paramiko.Channel)
    client.get_transport.return_value = transport
    return client, transport


class _SocketChannel:
    """Socket-backed subset of Paramiko Channel used to exercise the relay."""

    def __init__(self, sock: socket.socket) -> None:
        self._socket = sock

    @property
    def closed(self) -> bool:
        return self._socket.fileno() < 0

    def fileno(self) -> int:
        return self._socket.fileno()

    def setblocking(self, blocking: bool) -> None:
        self._socket.setblocking(blocking)

    def send_ready(self) -> bool:
        return not self.closed

    def send(self, data: bytes | bytearray) -> int:
        return self._socket.send(data)

    def recv(self, size: int) -> bytes:
        return self._socket.recv(size)

    def shutdown_write(self) -> None:
        self._socket.shutdown(socket.SHUT_WR)

    def shutdown_read(self) -> None:
        self._socket.shutdown(socket.SHUT_RD)

    def close(self) -> None:
        self._socket.close()


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(min(64 * 1024, size - len(chunks)))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


class TestSSHClientConnection:
    """Verify the supported high-level Paramiko connection path."""

    def test_uses_sshclient_connect_with_explicit_auth_and_timeouts(self) -> None:
        client, transport = _client_and_transport()
        pkey = MagicMock(spec=paramiko.PKey)
        config = _config(
            connect_timeout=11,
            banner_timeout=12,
            auth_timeout=13,
            channel_timeout=14,
            keepalive_interval=29,
        )
        forwarder = ParamikoTunnelForwarder(
            config,
            password="secret",
            pkey=pkey,
            client_factory=lambda: client,
        )

        try:
            assert forwarder.start() > 0
        finally:
            forwarder.stop()

        client.connect.assert_called_once_with(
            hostname="bastion.example.com",
            port=22,
            username="user",
            password="secret",
            pkey=pkey,
            timeout=11,
            banner_timeout=12,
            auth_timeout=13,
            channel_timeout=14,
            look_for_keys=False,
            allow_agent=False,
        )
        transport.connect.assert_not_called()
        transport.set_keepalive.assert_called_once_with(29)
        first_open = transport.open_channel.call_args_list[0]
        assert first_open.args == ("direct-tcpip",)
        assert first_open.kwargs["dest_addr"] == ("database.internal", 5432)
        assert first_open.kwargs["timeout"] == 14

    def test_channel_preflight_failure_does_not_publish_listener(self) -> None:
        client, transport = _client_and_transport()
        transport.open_channel.side_effect = paramiko.SSHException(
            "Timeout opening channel"
        )
        forwarder = ParamikoTunnelForwarder(
            _config(),
            password="secret",
            client_factory=lambda: client,
        )

        with pytest.raises(SSHTunnelError) as exc_info:
            forwarder.start()

        assert exc_info.value.code == SSHTunnelErrorCode.CHANNEL
        assert forwarder.local_bind_port is None
        assert not forwarder.is_active
        client.close.assert_called()

    @pytest.mark.parametrize(
        ("exception", "code"),
        [
            (
                paramiko.AuthenticationException("bad credentials"),
                SSHTunnelErrorCode.AUTH,
            ),
            (
                paramiko.BadHostKeyException(
                    "host",
                    MagicMock(spec=paramiko.PKey),
                    MagicMock(spec=paramiko.PKey),
                ),
                SSHTunnelErrorCode.HOST_KEY,
            ),
            (OSError("connection refused"), SSHTunnelErrorCode.CONNECT),
        ],
    )
    def test_connect_failures_are_classified_without_details(
        self,
        exception: Exception,
        code: SSHTunnelErrorCode,
    ) -> None:
        client, _ = _client_and_transport()
        client.connect.side_effect = exception
        forwarder = ParamikoTunnelForwarder(
            _config(),
            password="secret",
            client_factory=lambda: client,
        )

        with pytest.raises(SSHTunnelError) as exc_info:
            forwarder.start()

        assert exc_info.value.code == code
        assert "secret" not in str(exc_info.value)
        assert "bastion.example.com" not in str(exc_info.value)

    def test_strict_host_key_uses_read_only_known_hosts(self, tmp_path: Path) -> None:
        client, _ = _client_and_transport()
        known_hosts = tmp_path / "known_hosts"
        known_hosts.touch()
        forwarder = ParamikoTunnelForwarder(
            _config(strict_host_key=True, known_hosts_path=str(known_hosts)),
            password="secret",
            client_factory=lambda: client,
        )

        try:
            forwarder.start()
        finally:
            forwarder.stop()

        assert client.load_system_host_keys.call_count == 2
        client.load_system_host_keys.assert_any_call()
        client.load_system_host_keys.assert_any_call(str(known_hosts))
        policy = client.set_missing_host_key_policy.call_args.args[0]
        assert isinstance(policy, paramiko.RejectPolicy)
        client.load_host_keys.assert_not_called()

    def test_compatibility_host_key_policy_does_not_read_or_write_known_hosts(
        self,
    ) -> None:
        client, _ = _client_and_transport()
        forwarder = ParamikoTunnelForwarder(
            _config(),
            password="secret",
            client_factory=lambda: client,
        )

        try:
            forwarder.start()
        finally:
            forwarder.stop()

        client.load_system_host_keys.assert_not_called()
        client.load_host_keys.assert_not_called()
        client.save_host_keys.assert_not_called()

    def test_configured_local_port_and_idempotent_stop(self) -> None:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        configured_port = int(probe.getsockname()[1])
        probe.close()
        client, _ = _client_and_transport()
        forwarder = ParamikoTunnelForwarder(
            _config(local_port=configured_port),
            password="secret",
            client_factory=lambda: client,
        )

        assert forwarder.start() == configured_port
        forwarder.stop()
        forwarder.stop()

        assert not forwarder.is_active
        assert forwarder.local_bind_port is None

    def test_failed_handler_closes_only_its_local_connection(self) -> None:
        client, transport = _client_and_transport()
        transport.open_channel.side_effect = [
            MagicMock(spec=paramiko.Channel),
            paramiko.ChannelException(1, "administratively prohibited"),
        ]
        forwarder = ParamikoTunnelForwarder(
            _config(),
            password="secret",
            client_factory=lambda: client,
        )

        try:
            port = forwarder.start()
            with socket.create_connection(("127.0.0.1", port), timeout=2) as local:
                local.settimeout(2)
                assert local.recv(1) == b""
            assert forwarder.is_active
        finally:
            forwarder.stop()


class TestTransportRecovery:
    """Verify recovery keeps the local endpoint and isolates active channels."""

    def test_inactive_transport_is_replaced_without_changing_listener_port(
        self,
    ) -> None:
        client_one, transport_one = _client_and_transport()
        client_two, transport_two = _client_and_transport()
        clients = iter([client_one, client_two])
        forwarder = ParamikoTunnelForwarder(
            _config(),
            password="secret",
            client_factory=lambda: next(clients),
        )

        try:
            port = forwarder.start()
            transport_one.is_active.return_value = False

            assert forwarder.ensure_active()
            assert forwarder.local_bind_port == port
            assert forwarder.is_active
            assert client_one.close.called
            assert transport_two.open_channel.call_count == 2
        finally:
            forwarder.stop()

    def test_channel_timeout_reconnects_once_before_relay(self) -> None:
        client_one, transport_one = _client_and_transport()
        client_two, transport_two = _client_and_transport()
        preflight = MagicMock(spec=paramiko.Channel)
        transport_one.open_channel.side_effect = [
            preflight,
            paramiko.SSHException("Timeout opening channel"),
        ]
        clients = iter([client_one, client_two])
        forwarder = ParamikoTunnelForwarder(
            _config(),
            password="secret",
            client_factory=lambda: next(clients),
        )

        try:
            port = forwarder.start()
            lease = forwarder._acquire_channel(("127.0.0.1", 12345))
            lease.close()

            assert forwarder.local_bind_port == port
            assert client_one.close.called
            assert transport_two.open_channel.call_count == 2
        finally:
            forwarder.stop()

    def test_replacement_does_not_close_a_leased_transport_generation(self) -> None:
        client_one, transport_one = _client_and_transport()
        client_two, _ = _client_and_transport()
        active_channel = MagicMock(spec=paramiko.Channel)
        transport_one.open_channel.side_effect = [
            MagicMock(spec=paramiko.Channel),
            active_channel,
            paramiko.SSHException("Timeout opening channel"),
        ]
        clients = iter([client_one, client_two])
        forwarder = ParamikoTunnelForwarder(
            _config(),
            password="secret",
            client_factory=lambda: next(clients),
        )

        try:
            forwarder.start()
            first_lease = forwarder._acquire_channel(("127.0.0.1", 10001))
            replacement_lease = forwarder._acquire_channel(("127.0.0.1", 10002))

            assert not client_one.close.called
            replacement_lease.close()
            assert not client_one.close.called
            first_lease.close()
            assert client_one.close.called
        finally:
            forwarder.stop()

    def test_concurrent_recovery_creates_only_one_replacement(self) -> None:
        client_one, transport_one = _client_and_transport()
        client_two, transport_two = _client_and_transport()
        clients = iter([client_one, client_two])
        factory_calls = 0
        factory_lock = threading.Lock()

        def client_factory() -> MagicMock:
            nonlocal factory_calls
            with factory_lock:
                factory_calls += 1
                return next(clients)

        forwarder = ParamikoTunnelForwarder(
            _config(),
            password="secret",
            client_factory=client_factory,
        )
        errors: list[BaseException] = []

        try:
            forwarder.start()
            transport_one.is_active.return_value = False
            start = threading.Barrier(6)

            def recover() -> None:
                try:
                    start.wait()
                    forwarder.ensure_active()
                except BaseException as exc:  # pragma: no cover - assertion path
                    errors.append(exc)

            threads = [threading.Thread(target=recover) for _ in range(5)]
            for thread in threads:
                thread.start()
            start.wait()
            for thread in threads:
                thread.join(5)

            assert not errors
            assert all(not thread.is_alive() for thread in threads)
            assert factory_calls == 2
            assert transport_two.open_channel.call_count == 6
        finally:
            forwarder.stop()

    def test_stop_closes_a_replacement_that_was_already_connecting(self) -> None:
        client_one, transport_one = _client_and_transport()
        client_two, _ = _client_and_transport()
        connect_started = threading.Event()
        allow_connect = threading.Event()

        def blocking_connect(**_kwargs: object) -> None:
            connect_started.set()
            assert allow_connect.wait(5)

        client_two.connect.side_effect = blocking_connect
        clients = iter([client_one, client_two])
        forwarder = ParamikoTunnelForwarder(
            _config(),
            password="secret",
            client_factory=lambda: next(clients),
        )
        recovery_errors: list[BaseException] = []

        forwarder.start()
        transport_one.is_active.return_value = False

        def recover() -> None:
            try:
                forwarder.ensure_active()
            except BaseException as exc:
                recovery_errors.append(exc)

        recovery_thread = threading.Thread(target=recover)
        stop_thread = threading.Thread(target=forwarder.stop)
        recovery_thread.start()
        assert connect_started.wait(5)
        stop_thread.start()
        allow_connect.set()
        recovery_thread.join(5)
        stop_thread.join(5)

        assert not recovery_thread.is_alive()
        assert not stop_thread.is_alive()
        assert all(isinstance(exc, SSHTunnelError) for exc in recovery_errors)
        assert client_two.close.called
        assert forwarder._current_generation is None
        assert forwarder.local_bind_port is None
        assert not forwarder.is_active


class TestRelay:
    """Exercise bidirectional transfer, backpressure, and half-close behavior."""

    def test_large_bidirectional_payloads_and_half_closes(self) -> None:
        forwarder = ParamikoTunnelForwarder(_config(), password="secret")
        local_peer, local_forward = socket.socketpair()
        channel_socket, remote_peer = socket.socketpair()
        channel = _SocketChannel(channel_socket)
        relay = threading.Thread(
            target=forwarder._relay,
            args=(local_forward, channel),
            daemon=True,
        )
        relay.start()
        outbound = b"local-to-remote" * 100_000
        inbound = b"remote-to-local" * 100_000

        def send_and_half_close(sock: socket.socket, payload: bytes) -> None:
            sock.sendall(payload)
            sock.shutdown(socket.SHUT_WR)

        outbound_sender = threading.Thread(
            target=send_and_half_close,
            args=(local_peer, outbound),
        )
        inbound_sender = threading.Thread(
            target=send_and_half_close,
            args=(remote_peer, inbound),
        )
        outbound_sender.start()
        inbound_sender.start()

        try:
            assert _read_exact(remote_peer, len(outbound)) == outbound
            assert _read_exact(local_peer, len(inbound)) == inbound
            assert remote_peer.recv(1) == b""
            assert local_peer.recv(1) == b""
            outbound_sender.join(5)
            inbound_sender.join(5)
            relay.join(5)
            assert not outbound_sender.is_alive()
            assert not inbound_sender.is_alive()
            assert not relay.is_alive()
        finally:
            channel.close()
            for sock in (local_peer, local_forward, remote_peer):
                try:
                    sock.close()
                except OSError:
                    pass


@pytest.mark.skipif(not socket.has_ipv6, reason="IPv6 is unavailable")
def test_ipv6_listener_binds_loopback() -> None:
    """An IPv6 local host should select the IPv6 listener family."""
    client, _ = _client_and_transport()
    forwarder = ParamikoTunnelForwarder(
        _config(local_host="::1"),
        password="secret",
        client_factory=cast_client_factory(client),
    )
    try:
        assert forwarder.start() > 0
        assert forwarder.is_active
    except OSError as exc:
        pytest.skip(f"IPv6 loopback is unavailable: {exc}")
    finally:
        forwarder.stop()


def cast_client_factory(client: MagicMock) -> Callable[[], paramiko.SSHClient]:
    """Keep the IPv6 test factory readable under strict type checking."""
    return lambda: client
