import json
import select
import socket
import time

from gym_sts import exceptions
from gym_sts.spaces.observations import Observation


class _SocketEndpoint:
    def __init__(self, timeout: float):
        self.timeout = timeout
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(timeout)
        self.port = self.listener.getsockname()[1]
        self.conn = None
        self.file = None

    def accept(self, mode: str):
        if self.file is not None:
            return

        try:
            self.conn, _ = self.listener.accept()
        except socket.timeout as exc:
            raise exceptions.StSTimeoutError(
                f"Timed out after {self.timeout} seconds waiting for bridge connection."
            ) from exc

        self.conn.settimeout(self.timeout)
        self.file = self.conn.makefile(mode)

    def close(self) -> None:
        if self.file is not None:
            self.file.close()
            self.file = None
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        self.listener.close()


class SocketReceiver(_SocketEndpoint):
    def __init__(self, timeout: float):
        super().__init__(timeout)
        self.sleep_time = 0.1
        self.num_steps = max(1, int(timeout / self.sleep_time))

    def empty_fifo(self) -> None:
        self.accept("r")

        while True:
            ready, _, _ = select.select([self.conn], [], [], 0)
            if not ready:
                break

            line = self.file.readline()
            if not line:
                break

    def receive_game_state(self) -> dict:
        self.accept("r")

        message = ""
        for _ in range(self.num_steps):
            try:
                line = self.file.readline()
            except socket.timeout:
                line = ""

            if line:
                message += line
                try:
                    state = json.loads(message)
                    if state["ready_for_command"]:
                        return state
                    message = ""
                except json.decoder.JSONDecodeError:
                    pass

            time.sleep(self.sleep_time)

        raise exceptions.StSTimeoutError(
            f"Waited {self.timeout} seconds for game state to be ready "
            "for command, but it didn't happen."
        )


class SocketSender(_SocketEndpoint):
    def __init__(self, timeout: float):
        super().__init__(timeout)

    def _send_message(self, msg: str) -> None:
        self.accept("w")
        self.file.write(f"{msg}\n")
        self.file.flush()

    def send_ready(self) -> None:
        self._send_message("READY")

    def send_start(self, player_class: str, ascension: int, seed: str) -> None:
        self._send_message(f"START {player_class} {ascension} {seed}")

    def send_proceed(self) -> None:
        self._send_message("PROCEED")

    def send_choose(self, choice) -> None:
        self._send_message(f"CHOOSE {choice}")

    def send_click(self, x: int, y: int, left: bool = True) -> None:
        side = "left" if left else "right"
        self._send_message(f"CLICK {side} {x} {y}")

    def send_play(self, index, target) -> None:
        self._send_message(f"PLAY {index} {target}")

    def send_end(self) -> None:
        self._send_message("END")

    def send_potion(self, action, slot, target) -> None:
        self._send_message(f"POTION {action} {slot} {target}")

    def send_resign(self) -> None:
        self._send_message("RESIGN")

    def send_wait(self, frames: int) -> None:
        self._send_message(f"WAIT {frames}")

    def send_state(self) -> None:
        self._send_message("STATE")

    def send_basemod(self, command: str) -> None:
        self._send_message(f"BASEMOD {command}")

    def send_render(self, render: bool) -> None:
        self._send_message(f"RENDER {render}")


class SocketCommunicator:
    def __init__(self, timeout: float = 5):
        self.receiver = SocketReceiver(timeout)
        self.sender = SocketSender(timeout)
        self.command_port = self.sender.port
        self.state_port = self.receiver.port

    def _manual_command(self, action: str) -> Observation:
        self.receiver.empty_fifo()
        while True:
            try:
                self.sender._send_message(action)
                state = self.receiver.receive_game_state()
                break
            except Exception:
                print("E: do action state")
                action = "state"

        return Observation(state)

    def ready(self) -> None:
        self.sender.send_ready()

    def choose(self, choice) -> Observation:
        self.receiver.empty_fifo()
        self.sender.send_choose(choice)
        state = self.receiver.receive_game_state()
        return Observation(state)

    def click(self, x: int, y: int, left: bool = True) -> Observation:
        self.receiver.empty_fifo()
        self.sender.send_click(x, y, left=left)
        state = self.receiver.receive_game_state()
        return Observation(state)

    def end(self) -> Observation:
        self.receiver.empty_fifo()
        self.sender.send_end()
        state = self.receiver.receive_game_state()
        return Observation(state)

    def potion(self, action, slot, target) -> Observation:
        self.receiver.empty_fifo()
        self.sender.send_potion(action, slot, target)
        state = self.receiver.receive_game_state()
        return Observation(state)

    def proceed(self) -> Observation:
        self.receiver.empty_fifo()
        self.sender.send_proceed()
        state = self.receiver.receive_game_state()
        return Observation(state)

    def resign(self) -> Observation:
        self.receiver.empty_fifo()
        self.sender.send_resign()
        state = self.receiver.receive_game_state()
        return Observation(state)

    def start(self, player_class: str, ascension: int, seed: str) -> Observation:
        self.receiver.empty_fifo()
        self.sender.send_start(player_class, ascension, seed)

        for _ in range(3):
            state = self.receiver.receive_game_state()
            if state["in_game"]:
                return Observation(state)
            time.sleep(0.05)

        raise TimeoutError("Waited for game to start, but it didn't happen.")

    def state(self) -> Observation:
        self.receiver.empty_fifo()
        self.sender.send_state()
        state = self.receiver.receive_game_state()
        return Observation(state)

    def wait(self, frames: int) -> Observation:
        self.receiver.empty_fifo()
        self.sender.send_wait(frames)
        state = self.receiver.receive_game_state()
        return Observation(state)

    def basemod(self, command: str) -> Observation:
        self.receiver.empty_fifo()
        self.sender.send_basemod(command)
        state = self.receiver.receive_game_state()
        return Observation(state)

    def render(self, render: bool) -> None:
        self.sender.send_render(render)

    def close(self) -> None:
        self.sender.close()
        self.receiver.close()
