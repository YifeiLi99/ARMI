/* Relocatable entry points. No shell, registry discovery, or global PATH. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

static wchar_t command[32768];
static size_t used;

static int append(wchar_t value) {
    if (used + 1 >= sizeof(command) / sizeof(command[0])) return 0;
    command[used++] = value;
    command[used] = 0;
    return 1;
}

static int quote(const wchar_t *value) {
    if (used && !append(L' ')) return 0;
    if (!append(L'"')) return 0;
    for (;;) {
        size_t slashes = 0;
        while (*value == L'\\') { ++slashes; ++value; }
        size_t count = (*value == L'"' || !*value) ? slashes * 2 : slashes;
        for (size_t i = 0; i < count; ++i) if (!append(L'\\')) return 0;
        if (!*value) break;
        if (*value == L'"' && !append(L'\\')) return 0;
        if (!append(*value++)) return 0;
    }
    return append(L'"');
}

static int launch(int argc, wchar_t **argv) {
    wchar_t root[32768], python[32768], pointer[32768], script[4096];
    DWORD length = GetModuleFileNameW(NULL, root, 32768);
    if (!length || length >= 32768) return 2;
    wchar_t *name = wcsrchr(root, L'\\');
    if (!name) return 2;
    ++name;
    const wchar_t *code = NULL;
    if (!_wcsicmp(name, L"armi.exe")) code = L"from armi_runtime.cli import main; raise SystemExit(main())";
    if (!_wcsicmp(name, L"armi-mcp.exe")) code = L"from armi_runtime.mcp import main; raise SystemExit(main())";
    if (!_wcsicmp(name, L"armi-codex-runner.exe")) code = L"from armi_runtime.codex_runner_cli import main; raise SystemExit(main())";
    if (!_wcsicmp(name, L"armi-admin.exe")) code = L"from armi_admin.cli import main; raise SystemExit(main())";
    if (!_wcsicmp(name, L"armi-admin-mcp.exe")) code = L"from armi_admin.mcp.entrypoint import main; raise SystemExit(main())";
    if (!_wcsicmp(name, L"armi-setup.exe")) code = L"from armi_admin.setup_cli import main; raise SystemExit(main())";
    if (!_wcsicmp(name, L"armi-setup-mcp.exe")) code = L"from armi_admin.setup_cli import mcp_main; mcp_main()";
    if (!_wcsicmp(name, L"armi-desktop.exe")) code = L"from armi_admin.desktop import main; raise SystemExit(main())";
    if (!_wcsicmp(name, L"armi-install-control.exe")) code = L"from armi_admin.install_cli import main; raise SystemExit(main())";
    int installer = !_wcsicmp(name, L"armi-install-control.exe");
    if (!code) return 2;
    name[-1] = 0;
    if (swprintf_s(pointer, 32768, L"%s\\.current-version", root) < 0) return 2;
    HANDLE file = CreateFileW(pointer, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, NULL, OPEN_EXISTING, 0, NULL);
    if (file != INVALID_HANDLE_VALUE) {
        char version[27] = {0};
        DWORD count = 0;
        BOOL read = ReadFile(file, version, 26, &count, NULL);
        CloseHandle(file);
        if (!read || count != 25 || version[24] != '\n') return 2;
        wchar_t identifier[25] = {0};
        for (int i = 0; i < 24; ++i) {
            if (!((version[i] >= '0' && version[i] <= '9') || (version[i] >= 'a' && version[i] <= 'f'))) return 2;
            identifier[i] = (wchar_t)version[i];
        }
        if (swprintf_s(pointer, 32768, L"%s\\versions\\%s", root, identifier) < 0) return 2;
        if (wcscpy_s(root, 32768, pointer)) return 2;
    } else if (GetLastError() != ERROR_FILE_NOT_FOUND) return 2;
    if (!SetEnvironmentVariableW(L"ARMI_INSTALLATION_ROOT", root)) return 2;
    if (swprintf_s(script, 4096, L"%s%s", installer ? L"" : L"from armi_admin.install_cli import recover_startup; recover_startup(); ", code) < 0) return 2;
#ifdef ARMI_GUI
    if (swprintf_s(python, 32768, L"%s\\runtime\\python\\pythonw.exe", root) < 0) return 2;
#else
    if (swprintf_s(python, 32768, L"%s\\runtime\\python\\python.exe", root) < 0) return 2;
#endif
    if (!quote(python) || !quote(L"-I") || !quote(L"-B") || !quote(L"-c") || !quote(script)) return 2;
    for (int i = 1; i < argc; ++i) if (!quote(argv[i])) return 2;
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
#ifndef ARMI_GUI
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
#endif
    if (!CreateProcessW(python, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &process)) return 2;
    CloseHandle(process.hThread);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD result = 2;
    GetExitCodeProcess(process.hProcess, &result);
    CloseHandle(process.hProcess);
    return (int)result;
}

#ifdef ARMI_GUI
int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR line, int show) {
    (void)instance; (void)previous; (void)line; (void)show;
    int count;
    wchar_t **arguments = CommandLineToArgvW(GetCommandLineW(), &count);
    if (!arguments) return 2;
    int result = launch(count, arguments);
    LocalFree(arguments);
    return result;
}
#else
int wmain(int argc, wchar_t **argv) { return launch(argc, argv); }
#endif
