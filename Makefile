.PHONY: test test-gui demo install install-udev
PREFIX ?= $(HOME)/.local
PYTHON ?= python3

test:
	QT_QPA_PLATFORM=offscreen $(PYTHON) -m unittest discover -s tests -v

test-gui:
	QT_QPA_PLATFORM=offscreen $(PYTHON) -m unittest discover -s tests -p 'test_gui.py' -v

demo:
	$(PYTHON) -m tecknet --demo gui

install:
	install -d $(DESTDIR)$(PREFIX)/share/tecknet-gm2793/tecknet $(DESTDIR)$(PREFIX)/bin $(DESTDIR)$(PREFIX)/share/applications
	install -m 0644 tecknet/*.py $(DESTDIR)$(PREFIX)/share/tecknet-gm2793/tecknet/
	install -m 0755 packaging/tecknet-mouse $(DESTDIR)$(PREFIX)/bin/tecknet-mouse
	install -m 0644 packaging/tecknet-mouse.desktop $(DESTDIR)$(PREFIX)/share/applications/

install-udev:
	install -m 0644 packaging/70-tecknet-gm2793.rules $(DESTDIR)/etc/udev/rules.d/
