#!/usr/bin/env python3

from __future__ import annotations

import socket
import sys
import threading


def pump_commands(command_port: int) -> None:
    with socket.create_connection(("127.0.0.1", command_port)) as sock:
        while True:
            data = sock.recv(65536)
            if not data:
                break
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()


def pump_states(state_port: int) -> None:
    with socket.create_connection(("127.0.0.1", state_port)) as sock:
        while True:
            data = sys.stdin.buffer.readline()
            if not data:
                break
            sock.sendall(data)


def main() -> None:
    command_port = int(sys.argv[1])
    state_port = int(sys.argv[2])

    command_thread = threading.Thread(
        target=pump_commands, args=(command_port,), daemon=True
    )
    command_thread.start()

    pump_states(state_port)


if __name__ == "__main__":
    main()
