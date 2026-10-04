"""Native Linux desktop launcher and command-line configuration tools."""
import argparse
import json
from pathlib import Path

from .controller import Controller, import_profile, decode_native_profile
from .hid import HidDevice, SimulatedDevice, discover
from .protocol import (DPI_VALUES, POLLING, DEFAULT_BUTTONS, button_code,
                       macro_button, parse_macro)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Native TeckNet GM2793-1 Linux configuration')
    parser.add_argument('--demo', action='store_true', help='Use an in-memory mouse; never open hardware')
    parser.add_argument('--device-index', type=int, default=0)
    sub = parser.add_subparsers(dest='action')
    sub.add_parser('list', help='Find matching Linux HID interfaces')
    sub.add_parser('gui', help='Open the native Linux desktop application')
    sub.choices['gui'].add_argument('--skin-dir', type=Path,
                                    help='Optional folder of original skin images; no executables are used')
    sub.add_parser('info', help='Read firmware identity and active profile')
    show = sub.add_parser('show', help='Show decoded hardware profile settings')
    show.add_argument('profile', type=int, choices=(1, 2, 3))
    dump = sub.add_parser('dump', help='Back up the raw 520-byte general profile')
    dump.add_argument('profile', type=int, choices=(1, 2, 3))
    dump.add_argument('output', type=Path)
    select = sub.add_parser('select', help='Activate a hardware profile')
    select.add_argument('profile', type=int, choices=(1, 2, 3))
    config = sub.add_parser('set', help='Set polling, DPI stages or lighting directly')
    config.add_argument('profile', type=int, choices=(1, 2, 3))
    config.add_argument('--polling', type=int, choices=POLLING)
    config.add_argument('--dpi', type=int, nargs='+', choices=DPI_VALUES,
                        help='One to eight DPI values, using equal X/Y')
    config.add_argument('--active-slot', type=int, choices=range(1, 9))
    config.add_argument('--effect', type=int, choices=range(12))
    config.add_argument('--speed', type=int, choices=range(16))
    config.add_argument('--brightness', type=int, choices=range(16))
    config.add_argument('--color', help='#RRGGBB')
    export = sub.add_parser('export', help='Export a general profile to JSON')
    export.add_argument('profile', type=int, choices=(1, 2, 3))
    export.add_argument('output', type=Path)
    restore = sub.add_parser('import', help='Apply a native JSON profile or raw general backup')
    restore.add_argument('profile', type=int, choices=(1, 2, 3))
    restore.add_argument('input', type=Path)
    buttons = sub.add_parser('buttons', help='Write a complete twenty-entry button matrix')
    buttons.add_argument('profile', type=int, choices=(1, 2, 3))
    buttons.add_argument('input', type=Path, help='JSON array of twenty action names or integer codes')
    macro = sub.add_parser('macro', help='Upload a macro and assign it using a supplied button matrix')
    macro.add_argument('profile', type=int, choices=(1, 2, 3))
    macro.add_argument('buffer', type=int, choices=range(1, 15))
    macro.add_argument('input', type=Path, help='Native macro text file')
    macro.add_argument('--button', type=int, choices=range(1, 21), required=True)
    macro.add_argument('--matrix', type=Path, required=True,
                       help='JSON array of twenty existing button actions/codes')
    macro.add_argument('--mode', choices=('repeat', 'hold', 'toggle'), default='repeat')
    macro.add_argument('--repeats', type=int, default=1)
    bind = sub.add_parser('bind', help='Change one button while preserving the remaining assignments')
    bind.add_argument('profile', type=int, choices=(1, 2, 3))
    bind.add_argument('button', type=int, choices=range(1, 21))
    bind.add_argument('binding', help='Action name, key:CTRL+C, or raw:0x...')
    args = parser.parse_args(argv)
    action = args.action or 'gui'
    if action == 'list':
        print(json.dumps([{str(k): str(v) for k, v in group.items()} for group in discover()], indent=2))
        return 0
    device = None
    try:
        # Delay Qt imports so the CLI can run without GUI dependencies.
        if action == 'gui':
            try:
                from .gui import run
            except ImportError as exc:
                raise RuntimeError('Install the GUI dependency: python3 -m pip install "PySide6>=6.6,<7"') from exc
        device = SimulatedDevice() if args.demo else HidDevice(args.device_index)
        controller = Controller(device, args.demo)
        if action == 'gui':
            return run(controller, getattr(args, 'skin_dir', None))
        if action == 'info':
            print(json.dumps({'simulated': args.demo, 'firmware': controller.firmware,
                              'profile': controller.active}, indent=2))
            return 0
        if action == 'select':
            controller.select(args.profile)
            print(f'Active profile: {controller.active}')
            return 0
        original = controller.load(args.profile)
        edited = original.copy()
        if action == 'show':
            print(json.dumps(original.summary(), indent=2))
        elif action == 'dump':
            args.output.write_bytes(original.report)
            print(f'Saved general profile to {args.output}')
        elif action == 'export':
            controller.export(args.output, args.profile, original)
            print(f'Exported general profile to {args.output}')
        else:
            matrix, macros = None, None
            if action == 'set':
                if args.polling is not None:
                    edited.set_polling(args.polling)
                if args.dpi is not None:
                    if len(args.dpi) > 8:
                        raise ValueError('At most eight DPI stages are supported')
                    slots = original.dpi_slots()
                    for i, slot in enumerate(slots):
                        slot.update(enabled=i < len(args.dpi), x=args.dpi[min(i, len(args.dpi)-1)],
                                    y=args.dpi[min(i, len(args.dpi)-1)])
                    active = (args.active_slot or 1) - 1
                    edited.set_dpi(slots, False, active)
                elif args.active_slot is not None:
                    edited.set_dpi(original.dpi_slots(), original.separate_xy, args.active_slot - 1)
                if any(getattr(args, field) is not None for field in ('effect', 'speed', 'brightness', 'color')):
                    lighting = original.lighting()
                    for field in ('effect', 'speed', 'brightness', 'color'):
                        value = getattr(args, field)
                        if value is not None:
                            lighting[field] = value
                    if args.color is not None:
                        lighting['colors'] = [args.color]
                    edited.set_lighting(**lighting)
            elif action == 'import':
                if args.input.suffix.lower() == '.bin':
                    from .protocol import Profile
                    edited = Profile(args.input.read_bytes())
                else:
                    data = json.loads(args.input.read_text())
                    if isinstance(data, dict) and data.get('format') == 'tecknet-gm2793-native':
                        edited, matrix, assignments, library = decode_native_profile(data)
                        matrix, macros = controller.allocate_macros(args.profile, matrix, assignments, library)
                    else:
                        _, edited, matrix, macros = import_profile(args.input)
            elif action == 'bind':
                matrix = controller.load_buttons(args.profile)
                matrix[args.button - 1] = button_code(args.binding)
            else:
                path = args.input if action == 'buttons' else args.matrix
                values = json.loads(path.read_text())
                if not isinstance(values, list):
                    raise ValueError('Button matrix must be a JSON array')
                matrix = [button_code(value) if isinstance(value, str) else value for value in values]
                if action == 'macro':
                    if len(matrix) != 20:
                        raise ValueError('A button matrix must contain twenty entries')
                    text = args.input.read_text()
                    parse_macro(text)
                    matrix[args.button - 1] = macro_button(args.buffer, args.mode, args.repeats)
                    macros = {str(args.buffer): text}
            result = controller.apply(args.profile, original, edited, matrix, macros)
            print(json.dumps({'simulated': args.demo, 'profile': args.profile,
                              'settings': result.summary()}, indent=2))
        return 0
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        parser.exit(1, f'{exc}\n')
    finally:
        if device:
            # Reload can replace the transport after a physical reconnect.
            if 'controller' in locals():
                controller.device.close()
            device.close()


if __name__ == '__main__':
    raise SystemExit(main())
