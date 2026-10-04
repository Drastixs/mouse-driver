"""Authenticated localhost broker for the unchanged Windows UI under Wine."""
import hmac
import json
import time
import socket
import struct
import threading


def receive(sock, length):
    data = bytearray()
    while len(data) < length:
        part = sock.recv(length - len(data))
        if not part:
            raise ConnectionError('Bridge connection closed')
        data.extend(part)
    return bytes(data)


class Bridge:
    def __init__(self, device, token, trace=None):
        self.device, self.token = device, token
        self.trace = trace
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(8)
        self.socket.settimeout(.2)
        self.port = self.socket.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=4)
        self.socket.close()

    def run(self):
        # Sequential processing avoids concurrent accesses to the HID interfaces.
        while not self.stop.is_set():
            try:
                connection, _ = self.socket.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(2)
                try:
                    token = receive(connection, 32)
                    if not hmac.compare_digest(token, self.token.encode('ascii')):
                        continue
                    operation, length = struct.unpack('<BH', receive(connection, 3))
                    if length > 520 or operation not in (0, 1, 2):
                        raise ValueError('Invalid bridge request')
                    payload = receive(connection, length)
                    if operation == 0:
                        if payload:
                            raise ValueError('Ping must have no payload')
                        result = b''
                    else:
                        result = self.device.transfer(operation == 2, payload)
                        if self.trace:
                            self.trace.write(json.dumps({"time": time.time(), "operation": "GET" if operation == 2 else "SET", "request": payload.hex(), "response": result.hex()}) + "\n")
                            self.trace.flush()
                    connection.sendall(struct.pack('<BH', 1, len(result)) + result)
                except (OSError, ValueError, ConnectionError) as exc:
                    message = str(exc).encode('utf-8')[:1024]
                    try:
                        connection.sendall(struct.pack('<BH', 0, len(message)) + message)
                    except OSError:
                        pass
                    print(f'HID bridge: {exc}', flush=True)
