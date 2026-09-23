/* Early installed-entry diagnostics: no Python or ARMI DLL dependency. */
#include <shlobj.h>
#include <stdio.h>

static HANDLE diagnostic_file = INVALID_HANDLE_VALUE;
static HANDLE diagnostic_lease = INVALID_HANDLE_VALUE;
static wchar_t diagnostic_path[32768];
static char diagnostic_run[40];
static char diagnostic_version[40];
static unsigned long diagnostic_sequence;
static DWORD diagnostic_bytes;
static int diagnostic_emergency;
static const char *launch_stage = "arguments";
static DWORD launch_error;

static void diagnostic_unavailable(void) {
    const char text[] = "ARMI-LAUNCHER-DIAGNOSTIC-PERSISTENCE-UNAVAILABLE\n";
    DWORD written;
    WriteFile(GetStdHandle(STD_ERROR_HANDLE), text, sizeof(text) - 1, &written, NULL);
    OutputDebugStringA(text);
}

static int diagnostic_directory(const wchar_t *path) {
    if (CreateDirectoryW(path, NULL)) return 1;
    return GetLastError() == ERROR_ALREADY_EXISTS &&
        (GetFileAttributesW(path) & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) == FILE_ATTRIBUTE_DIRECTORY;
}

static int diagnostic_open(const wchar_t *base, int emergency) {
    wchar_t folder[32768], lease[32768];
    if (swprintf_s(folder, ARRAYSIZE(folder), L"%s\\control", base) < 0 || !diagnostic_directory(folder)) return 0;
    if (emergency) {
        if (wcscat_s(folder, ARRAYSIZE(folder), L"\\emergency") || !diagnostic_directory(folder)) return 0;
    }
    if (wcscat_s(folder, ARRAYSIZE(folder), L"\\logs") || !diagnostic_directory(folder)) return 0;
    if (swprintf_s(diagnostic_path, ARRAYSIZE(diagnostic_path), L"%s\\launcher-%S.jsonl", folder, diagnostic_run) < 0) return 0;
    if (swprintf_s(lease, ARRAYSIZE(lease), L"%s\\launcher-%S.lease", folder, diagnostic_run) < 0) return 0;
    diagnostic_lease = CreateFileW(lease, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    if (diagnostic_lease == INVALID_HANDLE_VALUE) return 0;
    OVERLAPPED range = {0};
    DWORD written;
    if (!WriteFile(diagnostic_lease, "0", 1, &written, NULL) ||
        !LockFileEx(diagnostic_lease, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &range)) {
        CloseHandle(diagnostic_lease); diagnostic_lease = INVALID_HANDLE_VALUE; return 0;
    }
    diagnostic_file = CreateFileW(diagnostic_path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_DELETE, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    if (diagnostic_file == INVALID_HANDLE_VALUE) {
        CloseHandle(diagnostic_lease); diagnostic_lease = INVALID_HANDLE_VALUE; return 0;
    }
    diagnostic_emergency = emergency;
    return 1;
}

static void diagnostic_initialize(void) {
    union { PACKAGE_ID alignment; BYTE bytes[4096]; } buffer;
    UINT32 length = sizeof(buffer);
    LONG status = GetCurrentPackageId(&length, buffer.bytes);
    if (status == APPMODEL_ERROR_NO_PACKAGE) return;
    if (status != ERROR_SUCCESS) { diagnostic_unavailable(); return; }
    PACKAGE_ID *package = (PACKAGE_ID *)buffer.bytes;
    const wchar_t *directory = NULL;
    if (!wcscmp(package->name, L"YifeiLi99.ARMI")) directory = L"ARMI";
    else if (!wcscmp(package->name, L"YifeiLi99.ARMI.Acceptance")) directory = L"ARMI.Acceptance";
    else if (!wcscmp(package->name, L"YifeiLi99.ARMI.MsixAcceptance")) directory = L"ARMI.MsixAcceptance";
    if (!directory) { diagnostic_unavailable(); return; }
    sprintf_s(diagnostic_version, sizeof(diagnostic_version), "%u.%u.%u.%u", package->version.Major, package->version.Minor, package->version.Build, package->version.Revision);
    GUID id;
    wchar_t raw[40], base[32768];
    PWSTR local = NULL;
    if (FAILED(CoCreateGuid(&id)) || !StringFromGUID2(&id, raw, ARRAYSIZE(raw)) ||
        FAILED(SHGetKnownFolderPath(&FOLDERID_LocalAppData, 0, NULL, &local))) { diagnostic_unavailable(); return; }
    raw[37] = 0;
    WideCharToMultiByte(CP_UTF8, 0, raw + 1, -1, diagnostic_run, sizeof(diagnostic_run), NULL, NULL);
    int valid = swprintf_s(base, ARRAYSIZE(base), L"%s\\%s", local, directory) >= 0;
    CoTaskMemFree(local);
    if (!valid || !diagnostic_directory(base) || (!diagnostic_open(base, 0) && !diagnostic_open(base, 1))) diagnostic_unavailable();
}

static void diagnostic_record(const char *event, const char *level, DWORD exit_code) {
    if (diagnostic_file == INVALID_HANDLE_VALUE) return;
    SYSTEMTIME at;
    char line[4096], message[768] = {0}, escaped[1536];
    wchar_t system_message[256];
    if (launch_error && FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        NULL, launch_error, 0, system_message, ARRAYSIZE(system_message), NULL)) {
        WideCharToMultiByte(CP_UTF8, 0, system_message, -1, message, sizeof(message), NULL, NULL);
    }
    size_t length = 0;
    for (size_t index = 0; message[index] && length + 2 < sizeof(escaped); ++index) {
        unsigned char value = (unsigned char)message[index];
        if (value == '"' || value == '\\') escaped[length++] = '\\';
        escaped[length++] = value < 32 ? ' ' : (char)value;
    }
    escaped[length] = 0;
    GetSystemTime(&at);
    ++diagnostic_sequence;
    int count = sprintf_s(line, sizeof(line),
        "{\"schema_kind\":\"armi.diagnostic-event\",\"event_id\":\"%s-%lu\",\"timestamp\":\"%04u-%02u-%02uT%02u:%02u:%02u.%03u+00:00\","
        "\"event\":\"%s\",\"message\":\"%s\",\"level\":\"%s\",\"service\":\"armi-launcher\",\"component\":\"windows-launcher\","
        "\"environment_id\":\"unbound\",\"run_id\":\"%s\",\"pid\":%lu,\"sequence\":%lu,\"version\":\"%s\",\"sink_mode\":\"%s\","
        "\"details\":{\"phase\":\"%s\",\"winerror\":%lu,\"system_message\":\"%s\",\"exit_code\":%lu}}\n",
        diagnostic_run, diagnostic_sequence, at.wYear, at.wMonth, at.wDay, at.wHour, at.wMinute, at.wSecond, at.wMilliseconds,
        event, event, level, diagnostic_run, GetCurrentProcessId(), diagnostic_sequence, diagnostic_version,
        diagnostic_emergency ? "emergency" : "file", launch_stage, launch_error, escaped, exit_code);
    DWORD written;
    if (count <= 0 || !WriteFile(diagnostic_file, line, (DWORD)count, &written, NULL) || written != (DWORD)count || !FlushFileBuffers(diagnostic_file)) diagnostic_unavailable();
    else diagnostic_bytes += written;
}

static void diagnostic_close(void) {
    if (diagnostic_file == INVALID_HANDLE_VALUE) return;
    CloseHandle(diagnostic_file); diagnostic_file = INVALID_HANDLE_VALUE;
    wchar_t *extension = wcsrchr(diagnostic_path, L'.');
    if (extension && wcscpy_s(extension, ARRAYSIZE(diagnostic_path) - (size_t)(extension - diagnostic_path), L".summary.json") == 0) {
        HANDLE summary = CreateFileW(diagnostic_path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
        char text[100]; DWORD written;
        int count = sprintf_s(text, sizeof(text), "{\"closed\":true,\"bytes\":%lu}\n", diagnostic_bytes);
        if (summary != INVALID_HANDLE_VALUE) { WriteFile(summary, text, (DWORD)count, &written, NULL); CloseHandle(summary); }
        else diagnostic_unavailable();
    }
    if (diagnostic_lease != INVALID_HANDLE_VALUE) { CloseHandle(diagnostic_lease); diagnostic_lease = INVALID_HANDLE_VALUE; }
}

static int launch_failed(DWORD error) { launch_error = error; return 2; }
