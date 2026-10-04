/* Vendor-compatible DLL: the UI runs under Wine, actual HID I/O runs on Linux. */
#include <winsock2.h>
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef int (__cdecl *caps_cb)(HANDLE, unsigned, unsigned, unsigned);
static int read_all(SOCKET s, char *buf, int n) {
    int done=0, count;
    while (done<n) { count=recv(s,buf+done,n-done,0); if(count<=0)return 0; done+=count; }
    return 1;
}
static int write_all(SOCKET s, const char *buf, int n) {
    int done=0, count;
    while (done<n) { count=send(s,buf+done,n-done,0); if(count<=0)return 0; done+=count; }
    return 1;
}
static int request(unsigned char op, void *buf, unsigned len) {
    WSADATA wsa; SOCKET s; struct sockaddr_in addr;
    char token[64], port[16]; unsigned char header[3], response[3];
    char error[1025]; int ok=0; unsigned size;
    if(!GetEnvironmentVariableA("TECKNET_BRIDGE_TOKEN",token,sizeof(token)) || strlen(token)!=32 ||
       !GetEnvironmentVariableA("TECKNET_BRIDGE_PORT",port,sizeof(port))) return 0;
    if(WSAStartup(MAKEWORD(2,2),&wsa))return 0;
    s=socket(AF_INET,SOCK_STREAM,0); if(s==INVALID_SOCKET){WSACleanup();return 0;}
    DWORD timeout=3000;
    setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,(char*)&timeout,sizeof(timeout));
    setsockopt(s,SOL_SOCKET,SO_SNDTIMEO,(char*)&timeout,sizeof(timeout));
    memset(&addr,0,sizeof(addr)); addr.sin_family=AF_INET; addr.sin_port=htons((unsigned short)atoi(port));
    addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    header[0]=op; header[1]=len&255; header[2]=(len>>8)&255;
    if(connect(s,(struct sockaddr*)&addr,sizeof(addr))==SOCKET_ERROR)goto end;
    if(!write_all(s,token,32)||!write_all(s,(char*)header,3)||
       (len && !write_all(s,(char*)buf,len))||!read_all(s,(char*)response,3))goto end;
    size=response[1]|(response[2]<<8);
    if(!response[0]) {
        if(size<=1024 && read_all(s,error,size)){error[size]=0;fprintf(stderr,"Linux HID: %s\n",error);}
        goto end;
    }
    if(op==2){if(size!=len||!read_all(s,buf,len))goto end;}else if(size)goto end;
    ok=1;
end:
    closesocket(s);WSACleanup();if(!ok)SetLastError(ERROR_DEVICE_NOT_CONNECTED);return ok;
}
__declspec(dllexport) int __cdecl FindHidDevice(LPCWSTR filter) {
    return filter && request(0,NULL,0);
}
__declspec(dllexport) HANDLE __cdecl OpenHidDevice(unsigned page,unsigned usage,LPCWSTR filter,
    caps_cb cb,LPWSTR path,size_t path_len,int debug,DWORD access,DWORD flags,int *count) {
    HANDLE h; unsigned sizes[]={6,520,8}; unsigned i;
    (void)debug;(void)access;(void)flags;
    if((page&0xffff)!=0xff00||usage!=1||!filter||!cb ||
       !wcsstr(filter,L"258")||!wcsstr(filter,L"1007")||!request(0,NULL,0))return NULL;
    for(i=0;i<3;i++) {
        h=CreateEventW(NULL,FALSE,FALSE,NULL);
        if(cb(h,8,8,sizes[i])) {
            if(path && path_len)_snwprintf(path,path_len,L"linux-hidraw-258a-1007");
            if(count)(*count)++;
            return h;
        }
        CloseHandle(h);
    }
    return NULL;
}
__declspec(dllexport) BOOLEAN __cdecl SetFeature(HANDLE h,void *buf,ULONG len){return h&&request(1,buf,len);}
__declspec(dllexport) BOOLEAN __cdecl GetFeature(HANDLE h,void *buf,ULONG len){return h&&request(2,buf,len);}
__declspec(dllexport) BOOLEAN __cdecl SetOutputReport(HANDLE h,void *buf,ULONG len){(void)h;(void)buf;(void)len;return FALSE;}
__declspec(dllexport) BOOLEAN __cdecl GetInputReport(HANDLE h,void *buf,ULONG len){(void)h;memset(buf,0,len);return FALSE;}
__declspec(dllexport) BOOLEAN __cdecl GetProductString(HANDLE h,PVOID buf,ULONG len){(void)h;_snwprintf(buf,len/sizeof(WCHAR),L"Gaming Mouse");return TRUE;}
__declspec(dllexport) BOOLEAN __cdecl GetProductID(HANDLE h,DWORD *id){(void)h;if(id)*id=0x258a1007;return TRUE;}
