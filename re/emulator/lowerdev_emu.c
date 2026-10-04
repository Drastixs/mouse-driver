/*
 * Drop-in replacement for the vendor's Lowerdev.dll that emulates a
 * TeckNet GM2793 (SinoWealth 258A:1007) on the HID feature-report level.
 *
 * Used only inside a Wine sandbox to (a) run the original OemDrv.exe without
 * hardware and (b) log every feature report the original app sends, so the
 * Linux implementation can be diffed against the vendor's own encoder.
 *
 * Build: i686-w64-mingw32-gcc -shared -O2 -o Lowerdev.dll lowerdev_emu.c lowerdev_emu.def
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>

#define RPT_CMD   0x05
#define RPT_DATA  0x04
#define CMD_LEN   6
#define DATA_LEN  0x208

typedef int (__cdecl *caps_cb)(HANDLE h, unsigned in_len, unsigned out_len, unsigned feat_len);

static HANDLE h_cmd, h_data;
static unsigned char last_cmd[CMD_LEN];
static unsigned char cfg[3][DATA_LEN];
static unsigned char active_profile = 1;
static FILE *logf;

static void log_hex(const char *tag, const unsigned char *buf, unsigned len)
{
    unsigned i, end = len;
    if (!logf) {
        logf = fopen("featlog.txt", "a");
        if (!logf)
            return;
    }
    while (end > 1 && buf[end - 1] == 0)
        end--;
    fprintf(logf, "%s len=%u:", tag, len);
    for (i = 0; i < end; i++)
        fprintf(logf, " %02x", buf[i]);
    fprintf(logf, "\n");
    fflush(logf);
}

static void init_profiles(void)
{
    static const unsigned char dpi_rgb[8][3] = {
        {255, 0, 0}, {0, 0, 255}, {0, 255, 0}, {255, 0, 255},
        {255, 255, 0}, {0, 255, 255}, {255, 255, 255}, {255, 128, 0},
    };
    int p, i;
    for (p = 0; p < 3; p++) {
        unsigned char *c = cfg[p] + 8;     /* payload starts at report offset 8 */
        cfg[p][0] = RPT_DATA;
        cfg[p][1] = (unsigned char)(0x11 + 0x10 * p);
        c[0] = 0x64;
        c[1] = 0x13;                        /* sensor id -> 0x3104 */
        c[2] = 0x03;                        /* 500 Hz */
        c[3] = 0x05 | (1 << 4);             /* 5 slots enabled, slot 1 active */
        c[4] = 0xe0;                        /* slots 6..8 disabled */
        c[5] = 2; c[6] = 4; c[7] = 8; c[8] = 12; c[9] = 16;
        for (i = 0; i < 8; i++)
            memcpy(c + 0x15 + i * 3, dpi_rgb[i], 3);
        c[0x2d] = 1;                        /* colorful streaming */
        c[0x2e] = 0x42;
    }
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)inst; (void)reserved;
    if (reason == DLL_PROCESS_ATTACH)
        init_profiles();
    return TRUE;
}

__declspec(dllexport) int __cdecl FindHidDevice(LPCWSTR filter)
{
    return filter && wcsstr(filter, L"258") ? 1 : 0;
}

__declspec(dllexport) HANDLE __cdecl
OpenHidDevice(unsigned usage_page, unsigned usage, LPCWSTR filter, caps_cb cb,
              LPWSTR path_out, size_t path_len, int debug, DWORD access,
              DWORD flags, int *count)
{
    HANDLE h;
    (void)usage; (void)debug; (void)access; (void)flags; (void)count;
    if ((usage_page & 0xffff) != 0xff00 || !filter || !cb)
        return NULL;
    if (!wcsstr(filter, L"258A") && !wcsstr(filter, L"258a"))
        return NULL;
    if (!(wcsstr(filter, L"1007")))
        return NULL;
    h = CreateEventW(NULL, FALSE, FALSE, NULL);
    if (cb(h, 8, 8, CMD_LEN)) {
        h_cmd = h;
    } else if (cb(h, 8, 8, DATA_LEN)) {
        h_data = h;
    } else {
        CloseHandle(h);
        return NULL;
    }
    if (path_out && path_len)
        _snwprintf(path_out, path_len, L"\\\\?\\hid#vid_258a&pid_1007#emu");
    return h;
}

__declspec(dllexport) BOOLEAN __cdecl SetFeature(HANDLE h, void *buf, ULONG len)
{
    unsigned char *b = buf;
    log_hex("SET", b, len);
    if (h && len == CMD_LEN && b[0] == RPT_CMD) {
        memcpy(last_cmd, b, CMD_LEN);
        if (b[1] == 0x02 && b[2] >= 1 && b[2] <= 3)
            active_profile = b[2];
        return TRUE;
    }
    if (h && b[0] == RPT_DATA && len == DATA_LEN) {
        int p = (b[1] >> 4) - 1;
        if ((b[1] & 0x0f) == 0x01 && p >= 0 && p < 3)
            memcpy(cfg[p], b, DATA_LEN);
        return TRUE;
    }
    return FALSE;
}

__declspec(dllexport) BOOLEAN __cdecl GetFeature(HANDLE h, void *buf, ULONG len)
{
    unsigned char *b = buf;
    if (h && len == CMD_LEN) {
        memset(b, 0, len);
        b[0] = RPT_CMD;
        b[1] = last_cmd[1];
        if (last_cmd[1] == 0x01) {          /* firmware id, must match Cfg PSD */
            b[2] = 0x32; b[3] = 0x37; b[4] = 0x36; b[5] = 0x34;
        } else if (last_cmd[1] == 0x02) {
            b[2] = active_profile;
        }
        log_hex("GET", b, len);
        return TRUE;
    }
    if (h && len == DATA_LEN) {
        int p = (last_cmd[1] >> 4) - 1;
        if ((last_cmd[1] & 0x0f) == 0x01 && p >= 0 && p < 3)
            memcpy(b, cfg[p], DATA_LEN);
        else
            memset(b, 0, len);
        b[0] = RPT_DATA;
        log_hex("GET", b, len);
        return TRUE;
    }
    return FALSE;
}

__declspec(dllexport) BOOLEAN __cdecl SetOutputReport(HANDLE h, void *buf, ULONG len)
{
    (void)h;
    log_hex("OUT", buf, len);
    return TRUE;
}

__declspec(dllexport) BOOLEAN __cdecl GetInputReport(HANDLE h, void *buf, ULONG len)
{
    (void)h;
    memset(buf, 0, len);
    return FALSE;
}

__declspec(dllexport) BOOLEAN __cdecl GetProductString(HANDLE h, PVOID buf, ULONG len)
{
    (void)h;
    _snwprintf(buf, len / sizeof(WCHAR), L"Gaming Mouse");
    return TRUE;
}

__declspec(dllexport) BOOLEAN __cdecl GetProductID(HANDLE h, DWORD *vid_pid)
{
    (void)h;
    if (vid_pid)
        *vid_pid = 0x258a1007;
    return TRUE;
}
