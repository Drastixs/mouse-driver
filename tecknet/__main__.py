import argparse
import fcntl
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from .hid import HidDevice, SimulatedDevice, discover
from .bridge import Bridge

ROOT = Path(__file__).resolve().parent.parent


def gui(device, demo, trace_path=None):
    cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache')) / 'tecknet-gm2793' / ('demo' if demo else 'device')
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / 'launcher.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('A TeckNet GUI is already running in this mode') from None
        return _gui(device, demo, trace_path, cache)


def _gui(device, demo, trace_path, cache):
    wine = shutil.which('wine')
    if not wine:
        raise RuntimeError('Install Wine with 32-bit support to run the original UI')
    library = ROOT / 'build/Lowerdev.dll'
    if not library.exists():
        raise RuntimeError('Run make bridge first')
    # Separate prefixes avoid the vendor mutex mixing real-device and demo sessions.
    app = cache / 'app'
    app.mkdir(parents=True, exist_ok=True)
    vendor = ROOT / 'vendor/original'
    if not (vendor/'OemDrv.exe').exists():
        raise RuntimeError('Missing vendor/original/OemDrv.exe and its assets')
    for name in ('OemDrv.exe','MenuEx.dll','InitSetup.dll','text.xml','text_en.xml','appico.ico'):
        shutil.copy2(vendor/name, app/name)
    shutil.copytree(vendor/'skins', app/'skins', dirs_exist_ok=True)
    shutil.copy2(library, app/'Lowerdev.dll')
    # Always seed the vendor configuration; keep profile files created by the UI.
    shutil.copy2(vendor/'Cfg.ini', app/'Cfg.ini')
    shutil.copy2(vendor/'text_en.xml', app/'text.xml')
    token = secrets.token_hex(16)
    trace = trace_path.open("w") if trace_path else None
    bridge = Bridge(device, token, trace)
    bridge.start()
    env = dict(os.environ, WINEPREFIX=str(cache/'prefix'), WINEARCH='win32',
               WINEDLLOVERRIDES='lowerdev=n', TECKNET_BRIDGE_TOKEN=token,
               TECKNET_BRIDGE_PORT=str(bridge.port))
    env.setdefault('WINEDEBUG', '-all')
    print('DEMO: simulated mouse; hardware is untouched' if demo else 'Connected to Linux hidraw; starting original TeckNet UI', flush=True)
    try:
        process = subprocess.Popen([wine, 'OemDrv.exe'], cwd=app, env=env)
        try:
            return process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return 130
    finally:
        bridge.close()
        if trace:
            trace.close()


def main():
    parser = argparse.ArgumentParser(description='TeckNet GM2793-1 Linux HID configuration')
    parser.add_argument('--demo', action='store_true', help='Use a simulated mouse, never hardware')
    parser.add_argument('--device-index', type=int, default=0)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('list', help='Find matching Linux HID interfaces')
    gui_parser = sub.add_parser('gui', help='Run the exact vendor UI through the Linux HID bridge')
    gui_parser.add_argument('--trace', type=Path, help='Record feature transfers as JSON lines')
    sub.add_parser('info', help='Read firmware identifier and current hardware profile')
    dump = sub.add_parser('dump', help='Back up a raw profile feature report')
    dump.add_argument('profile', type=int, choices=(1,2,3))
    dump.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.action == 'list':
        print(json.dumps([{str(k):str(v) for k,v in group.items()} for group in discover()], indent=2))
        return 0
    device = None
    try:
        device = SimulatedDevice() if args.demo else HidDevice(args.device_index)
        if args.action == 'gui':
            return gui(device, args.demo, args.trace)
        if args.action == 'info':
            firmware = device.command(1)
            mode = device.command(2)
            print(json.dumps({'simulated':args.demo, 'firmware':firmware[2:].hex(), 'profile':mode[2]}, indent=2))
        else:
            args.output.write_bytes(device.read_profile(args.profile))
            print(f'Saved 520 bytes to {args.output}')
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')
    finally:
        if device:
            device.close()


if __name__ == '__main__':
    raise SystemExit(main())
