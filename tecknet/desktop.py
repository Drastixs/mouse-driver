"""Optional GNOME desktop controls; mouse firmware is desktop independent."""
import ast
import os
import shutil
import subprocess


class DesktopSettings:
    SCHEMA = 'org.gnome.desktop.peripherals.mouse'

    def __init__(self, demo=False):
        self.demo = demo
        self.simulated = {'speed': 0.0, 'accel-profile': 'default', 'left-handed': False,
                          'double-click': 400, 'natural-scroll': False}

    def command(self, *args):
        if not shutil.which('gsettings') or 'GNOME' not in os.environ.get('XDG_CURRENT_DESKTOP', '').upper():
            raise RuntimeError('Use your desktop’s Mouse settings for pointer speed and scrolling. '
                               'Direct controls here are available on GNOME.')
        try:
            result = subprocess.run(['gsettings', *args], capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Desktop settings did not respond') from exc
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'Desktop settings could not be changed')
        return result.stdout.strip()

    def read(self):
        if self.demo:
            return dict(self.simulated)
        values = {}
        for key in self.simulated:
            value = self.command('get', self.SCHEMA, key)
            values[key] = {'true': True, 'false': False}.get(value, value)
            if type(values[key]) is str:
                values[key] = ast.literal_eval(value)
        return values

    def write(self, settings):
        if set(settings) != set(self.simulated):
            raise ValueError('Incomplete desktop settings')
        if not -1 <= settings['speed'] <= 1 or settings['accel-profile'] not in ('default', 'flat', 'adaptive'):
            raise ValueError('Invalid pointer speed or acceleration')
        if type(settings['double-click']) is not int or not 100 <= settings['double-click'] <= 1000:
            raise ValueError('Invalid double-click interval')
        for key in ('left-handed', 'natural-scroll'):
            if type(settings[key]) is not bool:
                raise ValueError('Invalid desktop switch')
        if self.demo:
            self.simulated = dict(settings)
            return
        previous = self.read()
        for key in settings:
            if self.command('writable', self.SCHEMA, key) != 'true':
                raise RuntimeError(f'The desktop locks the {key} setting')
        changed = []
        try:
            for key, value in settings.items():
                self.command('set', self.SCHEMA, key, str(value).lower() if type(value) is bool else str(value))
                changed.append(key)
        except (RuntimeError, OSError):
            for key in changed:
                value = previous[key]
                self.command('set', self.SCHEMA, key, str(value).lower() if type(value) is bool else str(value))
            raise
