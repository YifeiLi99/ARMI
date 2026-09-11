/* Relocatable entry points. No shell, registry discovery, or global PATH. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <appmodel.h>
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
    wchar_t root[32768], python[32768], script[4096];
    DWORD length = GetModuleFileNameW(NULL, root, 32768);
    if (!length || length >= 32768) return 2;
    wchar_t *name = wcsrchr(root, L'\\');
    if (!name) return 2;
    ++name;
    int machine = argc > 1 && _wcsicmp(argv[1], L"settings") && _wcsicmp(argv[1], L"--background") && _wcsicmp(argv[1], L"--environment-root") && _wcsicmp(argv[1], L"--installation-root");
    HANDLE input = GetStdHandle(STD_INPUT_HANDLE);
    HANDLE output = GetStdHandle(STD_OUTPUT_HANDLE);
    HANDLE error = GetStdHandle(STD_ERROR_HANDLE);
    if (machine) {
        AttachConsole(ATTACH_PARENT_PROCESS);
        if (input && input != INVALID_HANDLE_VALUE) SetStdHandle(STD_INPUT_HANDLE, input);
        if (output && output != INVALID_HANDLE_VALUE) SetStdHandle(STD_OUTPUT_HANDLE, output);
        if (error && error != INVALID_HANDLE_VALUE) SetStdHandle(STD_ERROR_HANDLE, error);
    }
    name[-1] = 0;
    UINT32 capacity = 32768;
    LONG packaged = GetCurrentPackagePath(&capacity, root);
    if (packaged != ERROR_SUCCESS && packaged != APPMODEL_ERROR_NO_PACKAGE) return 2;
    int uninstall = argc == 3 && !_wcsicmp(argv[1], L"--uninstall-package");
    if (packaged == ERROR_SUCCESS && !uninstall) {
        wchar_t family[PACKAGE_FAMILY_NAME_MAX_LENGTH + 1], eventName[256];
        UINT32 familyLength = ARRAYSIZE(family);
        if (GetCurrentPackageFamilyName(&familyLength, family) != ERROR_SUCCESS) return 2;
        if (swprintf_s(eventName, ARRAYSIZE(eventName), L"Local\\%s.uninstalling", family) < 0) return 2;
        HANDLE removing = OpenEventW(SYNCHRONIZE, FALSE, eventName);
        if (removing) { CloseHandle(removing); return 2; }
    }
    if (argc == 3 && (uninstall || !_wcsicmp(argv[1], L"--environment-host") || !_wcsicmp(argv[1], L"--apply-update"))) {
        if (packaged != ERROR_SUCCESS) return 2;
        wchar_t libraryPath[32768];
        if (swprintf_s(libraryPath, 32768, L"%s\\armi_windows.dll", root) < 0) return 2;
        HMODULE library = LoadLibraryExW(libraryPath, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (!library) return 2;
        typedef HRESULT (__stdcall *Host)(const wchar_t *);
        Host host = (Host)GetProcAddress(library, uninstall ? "armi_uninstall_package" : !_wcsicmp(argv[1], L"--environment-host") ? "armi_environment_host" : "armi_restart_update");
        HRESULT result = host ? host(argv[2]) : E_FAIL;
        FreeLibrary(library);
        if (result != S_FALSE || _wcsicmp(argv[1], L"--apply-update")) return SUCCEEDED(result) ? 0 : 2;
        argc = 1;
        machine = 0;
    }
    if (!SetEnvironmentVariableW(L"ARMI_INSTALLATION_ROOT", root)) return 2;
    wchar_t launcherPid[32];
    if (swprintf_s(launcherPid, 32, L"%lu", GetCurrentProcessId()) < 0) return 2;
    if (!SetEnvironmentVariableW(L"ARMI_LAUNCHER_PID", launcherPid)) return 2;
    if (wcscpy_s(script, 4096, L"armi_app")) return 2;
    if (swprintf_s(python, 32768, L"%s\\runtime\\python\\%s", root, machine ? L"python.exe" : L"pythonw.exe") < 0) return 2;
    if (!quote(python) || !quote(L"-I") || !quote(L"-B") || !quote(L"-X") || !quote(L"utf8") || !quote(L"-m") || !quote(script)) return 2;
    for (int i = 1; i < argc; ++i) if (!quote(argv[i])) return 2;
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    if (machine) {
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
        startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
        startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    }
    BOOL created = CreateProcessW(python, command, NULL, NULL, machine, machine ? CREATE_NO_WINDOW : 0, NULL, NULL, &startup, &process);
    if (!created) return 2;
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
