.PHONY: bridge test demo
bridge: build/Lowerdev.dll
build/Lowerdev.dll: re/emulator/lowerdev_linux.c re/emulator/lowerdev_emu.def
	mkdir -p build
	i686-w64-mingw32-gcc -shared -O2 -Wall -Wextra -Werror -o $@ $^ -lws2_32

test:
	python3 -m unittest discover -s tests -v

demo: bridge
	python3 -m tecknet --demo gui
