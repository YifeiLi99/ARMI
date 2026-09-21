// Restricted ABI for the packaged Python application. No shell or arbitrary commands.
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <appmodel.h>
#include <shlobj.h>
#include <appxpackaging.h>
#include <shlwapi.h>
#include <softpub.h>
#include <wintrust.h>
#include <tlhelp32.h>
#include <winrt/Windows.ApplicationModel.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Foundation.Collections.h>
#include <winrt/Windows.Data.Json.h>
#include <winrt/Windows.Management.Deployment.h>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

using namespace winrt;
using namespace Windows::ApplicationModel;
using namespace Windows::Data::Json;

namespace {
struct Apartment {
    Apartment() { init_apartment(apartment_type::multi_threaded); }
    ~Apartment() {
        // Python does not keep a COM apartment alive between ABI calls. Release
        // cached WinRT factories before COM unloads their implementing DLLs.
        clear_factory_cache();
        uninit_apartment();
    }
};

struct Handle {
    HANDLE value = nullptr;
    explicit Handle(HANDLE handle) : value(handle) {
        if (!value || value == INVALID_HANDLE_VALUE) throw_last_error();
    }
    ~Handle() { if (value) CloseHandle(value); }
    Handle(Handle const&) = delete;
};

struct DeploymentGate {
    Handle mutex;
    DeploymentGate() : mutex(CreateMutexW(nullptr, FALSE,
        (L"Local\\" + std::wstring(Package::Current().Id().FamilyName()) + L".deployment-gate").c_str())) {
        DWORD result = WaitForSingleObject(mutex.value, 30000);
        if (result != WAIT_OBJECT_0 && result != WAIT_ABANDONED) throw hresult_error(HRESULT_FROM_WIN32(ERROR_BUSY));
    }
    ~DeploymentGate() { ReleaseMutex(mutex.value); }
};

JsonObject read_json(std::filesystem::path const& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input || std::filesystem::file_size(path) > 4 * 1024 * 1024) throw hresult_invalid_argument(L"MSIX-CONTROL-FILE");
    std::string value((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    return JsonObject::Parse(to_hstring(value));
}

std::wstring job_name(std::wstring const& environment) {
    if (environment.size() != 36 || environment.find_first_not_of(L"0123456789abcdef-") != std::wstring::npos) {
        throw hresult_invalid_argument(L"MSIX-HOST-ENVIRONMENT-ID");
    }
    return L"Local\\" + std::wstring(Package::Current().Id().FamilyName()) + L"." + environment;
}

bool host_ready(std::wstring const& name) {
    HANDLE ready = OpenEventW(SYNCHRONIZE, FALSE, (name + L".ready").c_str());
    if (!ready) return false;
    bool signaled = WaitForSingleObject(ready, 0) == WAIT_OBJECT_0;
    CloseHandle(ready);
    return signaled;
}

void activate_host(std::wstring const& environment) {
    auto name = job_name(environment);
    if (host_ready(name)) return;
    com_ptr<IApplicationActivationManager> activation;
    check_hresult(CoCreateInstance(CLSID_ApplicationActivationManager, nullptr, CLSCTX_LOCAL_SERVER,
        __uuidof(IApplicationActivationManager), activation.put_void()));
    std::wstring app = std::wstring(Package::Current().Id().FamilyName()) + L"!ARMI";
    std::wstring arguments = L"--environment-host " + environment;
    DWORD pid;
    check_hresult(activation->ActivateApplication(app.c_str(), arguments.c_str(), AO_NOERRORUI, &pid));
    auto deadline = GetTickCount64() + 15000;
    do {
        if (host_ready(name)) return;
        Sleep(20);
    } while (GetTickCount64() < deadline);
    throw hresult_error(HRESULT_FROM_WIN32(ERROR_TIMEOUT));
}

std::filesystem::path package_data_root();

struct ProcessAttributes {
    std::vector<std::byte> storage;
    LPPROC_THREAD_ATTRIBUTE_LIST list;
    ProcessAttributes() {
        SIZE_T size = 0;
        InitializeProcThreadAttributeList(nullptr, 3, 0, &size);
        storage.resize(size);
        list = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
        check_bool(InitializeProcThreadAttributeList(list, 3, 0, &size));
    }
    ~ProcessAttributes() { DeleteProcThreadAttributeList(list); }
    void set(DWORD_PTR key, void* value, SIZE_T size) {
        check_bool(UpdateProcThreadAttribute(list, 0, key, value, size, nullptr, nullptr));
    }
};

struct HostHandles {
    HANDLE host;
    HANDLE values[3]{};
    explicit HostHandles(HANDLE process) : host(process) {}
    ~HostHandles() {
        for (auto handle : values) if (handle) {
            HANDLE local = nullptr;
            if (DuplicateHandle(host, handle, GetCurrentProcess(), &local, 0, FALSE,
                DUPLICATE_CLOSE_SOURCE | DUPLICATE_SAME_ACCESS)) CloseHandle(local);
        }
    }
};

JsonObject spawn_child(JsonObject const& request) {
    DeploymentGate gate;
    auto environment = std::wstring(request.GetNamedString(L"environment_id"));
    auto name = job_name(environment);
    DWORD pid = 0;
    auto window = FindWindowW(L"ArmiEnvironmentHost", environment.c_str());
    if (!window || !GetWindowThreadProcessId(window, &pid) || !host_ready(name)) {
        throw hresult_invalid_argument(L"MSIX-HOST-NOT-READY");
    }
    Handle host(OpenProcess(PROCESS_CREATE_PROCESS | PROCESS_DUP_HANDLE |
        PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid));
    wchar_t family[PACKAGE_FAMILY_NAME_MAX_LENGTH + 1];
    UINT32 length = ARRAYSIZE(family);
    if (GetPackageFamilyName(host.value, &length, family) != ERROR_SUCCESS ||
        std::wstring_view(family) != Package::Current().Id().FamilyName()) {
        throw hresult_access_denied(L"MSIX-HOST-PACKAGE-BOUNDARY");
    }
    auto executable = std::filesystem::canonical(std::wstring(request.GetNamedString(L"executable")));
    bool permitted = false;
    for (auto root : {std::filesystem::path(Package::Current().InstalledPath().c_str()), package_data_root()}) {
        auto prefix = std::filesystem::canonical(root).wstring() + L"\\";
        auto path = executable.wstring();
        permitted |= path.size() > prefix.size() && !_wcsnicmp(path.c_str(), prefix.c_str(), prefix.size());
    }
    DWORD flags = static_cast<DWORD>(request.GetNamedNumber(L"creationflags"));
    if (!permitted || flags & ~(CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)) {
        throw hresult_invalid_argument(L"MSIX-HOST-PROCESS-BOUNDARY");
    }
    auto handles = request.GetNamedArray(L"handles");
    if (handles.Size() != 3) throw hresult_invalid_argument(L"MSIX-HOST-STDIO");
    HostHandles inherited(host.value);
    for (UINT32 index = 0; index < 3; ++index) {
        auto source = reinterpret_cast<HANDLE>(static_cast<UINT_PTR>(handles.GetNumberAt(index)));
        check_bool(DuplicateHandle(GetCurrentProcess(), source, host.value,
            &inherited.values[index], 0, TRUE, DUPLICATE_SAME_ACCESS));
    }
    Handle job(OpenJobObjectW(JOB_OBJECT_ASSIGN_PROCESS | JOB_OBJECT_QUERY, FALSE, name.c_str()));
    ProcessAttributes attributes;
    attributes.set(PROC_THREAD_ATTRIBUTE_PARENT_PROCESS, &host.value, sizeof(host.value));
    attributes.set(PROC_THREAD_ATTRIBUTE_JOB_LIST, &job.value, sizeof(job.value));
    attributes.set(PROC_THREAD_ATTRIBUTE_HANDLE_LIST, inherited.values, sizeof(inherited.values));
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = inherited.values[0];
    startup.StartupInfo.hStdOutput = inherited.values[1];
    startup.StartupInfo.hStdError = inherited.values[2];
    startup.lpAttributeList = attributes.list;
    auto command = std::wstring(request.GetNamedString(L"command"));
    auto cwd = std::wstring(request.GetNamedString(L"cwd"));
    std::wstring variables;
    for (auto value : request.GetNamedArray(L"environment")) {
        variables += value.GetString();
        variables += L'\0';
    }
    variables += L'\0';
    PROCESS_INFORMATION process{};
    // The system-activated host supplies the parent job chain. MCP client jobs
    // never own these children; JOB_LIST establishes supervision at creation.
    check_bool(CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, TRUE,
        flags | EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED,
        variables.data(), cwd.empty() ? nullptr : cwd.c_str(), &startup.StartupInfo, &process));
    Handle processHandle(process.hProcess);
    Handle thread(process.hThread);
    try {
        JsonObject result;
        result.Insert(L"pid", JsonValue::CreateNumberValue(process.dwProcessId));
        result.Insert(L"handle", JsonValue::CreateNumberValue(static_cast<double>(reinterpret_cast<UINT_PTR>(process.hProcess))));
        if (ResumeThread(thread.value) != 1) throw hresult_invalid_argument(L"MSIX-HOST-RESUME");
        processHandle.value = nullptr; // transferred to the Python Popen instance
        return result;
    } catch (...) {
        TerminateProcess(process.hProcess, 1);
        throw;
    }
}

std::filesystem::path package_data_root() {
    auto name = std::wstring(Package::Current().Id().Name());
    if (name != L"YifeiLi99.ARMI" && name != L"YifeiLi99.ARMI.Acceptance" &&
        name != L"YifeiLi99.ARMI.MsixAcceptance") {
        throw hresult_invalid_argument(L"MSIX-PACKAGE-NAME");
    }
    PWSTR raw = nullptr;
    check_hresult(SHGetKnownFolderPath(FOLDERID_LocalAppData, KF_FLAG_DEFAULT, nullptr, &raw));
    auto root = std::filesystem::path(raw) / name.substr(10);
    CoTaskMemFree(raw);
    return root;
}

void require_idle_environments() {
    auto root = package_data_root();
    auto index = root / L"control/environments.yaml";
    if (!std::filesystem::exists(index)) return;
    auto registry = read_json(index);
    if (registry.GetNamedString(L"schema_kind") != L"armi.installation-environments") {
        throw hresult_invalid_argument(L"MSIX-ENVIRONMENT-REGISTRY");
    }
    for (auto const& value : registry.GetNamedArray(L"environments")) {
        auto environment = std::filesystem::path(value.GetString().c_str());
        if (environment.parent_path() != root / L"environments") throw hresult_invalid_argument(L"MSIX-ENVIRONMENT-BOUNDARY");
        auto state = read_json(environment / L".setup/operation.json");
        auto jobName = job_name(std::wstring(state.GetNamedString(L"environment_id")));
        HANDLE rawJob = OpenJobObjectW(JOB_OBJECT_QUERY, FALSE, jobName.c_str());
        if (!rawJob) {
            if (GetLastError() != ERROR_FILE_NOT_FOUND) throw_last_error();
            continue;
        }
        Handle job(rawJob);
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting{};
        check_bool(QueryInformationJobObject(job.value, JobObjectBasicAccountingInformation, &accounting, sizeof(accounting), nullptr));
        if (accounting.ActiveProcesses) throw hresult_error(HRESULT_FROM_WIN32(ERROR_BUSY));
    }
}

void require_plain_data_tree(std::filesystem::path const& root) {
    // Reject junctions/symlinks before any deletion. Neither the root nor its
    // ancestors may redirect cleanup into another installation or user folder.
    for (auto path = root; !path.empty(); path = path.parent_path()) {
        DWORD attributes = GetFileAttributesW(path.c_str());
        if (attributes == INVALID_FILE_ATTRIBUTES) {
            if (GetLastError() != ERROR_FILE_NOT_FOUND && GetLastError() != ERROR_PATH_NOT_FOUND) throw_last_error();
        } else if (attributes & FILE_ATTRIBUTE_REPARSE_POINT) {
            throw hresult_invalid_argument(L"MSIX-UNINSTALL-REPARSE-POINT");
        }
        if (path == path.parent_path()) break;
    }
    if (!std::filesystem::exists(root)) return;
    for (auto const& entry : std::filesystem::recursive_directory_iterator(root)) {
        DWORD attributes = GetFileAttributesW(entry.path().c_str());
        if (attributes == INVALID_FILE_ATTRIBUTES) throw_last_error();
        if (attributes & FILE_ATTRIBUTE_REPARSE_POINT) throw hresult_invalid_argument(L"MSIX-UNINSTALL-REPARSE-POINT");
    }
}

void close_package_clients() {
    // Admin has already stopped life. Close only this session's remaining
    // package clients, so GUI locks and persistent stdio servers cannot retain
    // data handles during removal. The deployment gate prevents new work.
    auto family = Package::Current().Id().FamilyName();
    DWORD session = 0;
    check_bool(ProcessIdToSessionId(GetCurrentProcessId(), &session));
    for (int pass = 0; pass < 8; ++pass) {
        bool found = false;
        Handle snapshot(CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0));
        PROCESSENTRY32W entry{sizeof(entry)};
        if (!Process32FirstW(snapshot.value, &entry)) throw_last_error();
        do {
            DWORD otherSession = 0;
            if (entry.th32ProcessID == GetCurrentProcessId() ||
                !ProcessIdToSessionId(entry.th32ProcessID, &otherSession) || otherSession != session) continue;
            HANDLE raw = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE | SYNCHRONIZE, FALSE, entry.th32ProcessID);
            if (!raw) continue; // Unrelated protected/system processes are not ours.
            Handle process(raw);
            wchar_t name[PACKAGE_FAMILY_NAME_MAX_LENGTH + 1];
            UINT32 length = ARRAYSIZE(name);
            if (GetPackageFamilyName(process.value, &length, name) != ERROR_SUCCESS || family != name) continue;
            found = true;
            if (!TerminateProcess(process.value, 0) && WaitForSingleObject(process.value, 0) != WAIT_OBJECT_0) throw_last_error();
            if (WaitForSingleObject(process.value, 10000) != WAIT_OBJECT_0) throw hresult_error(HRESULT_FROM_WIN32(ERROR_BUSY));
        } while (Process32NextW(snapshot.value, &entry));
        if (!found) return;
    }
    throw hresult_error(HRESULT_FROM_WIN32(ERROR_BUSY));
}

LRESULT CALLBACK host_window(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_QUERYENDSESSION) return TRUE;
    if (message == WM_ENDSESSION && wparam) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(window, message, wparam, lparam);
}
void text(JsonObject const& object, wchar_t const* key, std::wstring_view value) {
    object.Insert(key, JsonValue::CreateStringValue(value));
}

std::wstring version(PackageVersion const& value) {
    return std::to_wstring(value.Major) + L"." + std::to_wstring(value.Minor) + L"." +
        std::to_wstring(value.Build) + L"." + std::to_wstring(value.Revision);
}

void verify(std::wstring const& path) {
    WINTRUST_FILE_INFO file{sizeof(file)};
    file.pcwszFilePath = path.c_str();
    WINTRUST_DATA trust{sizeof(trust)};
    trust.dwUIChoice = WTD_UI_NONE;
    trust.fdwRevocationChecks = WTD_REVOKE_WHOLECHAIN;
    trust.dwUnionChoice = WTD_CHOICE_FILE;
    trust.pFile = &file;
    trust.dwStateAction = WTD_STATEACTION_VERIFY;
    trust.dwProvFlags = WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT;
    GUID policy = WINTRUST_ACTION_GENERIC_VERIFY_V2;
    LONG result = WinVerifyTrust(nullptr, &policy, &trust);
    trust.dwStateAction = WTD_STATEACTION_CLOSE;
    WinVerifyTrust(nullptr, &policy, &trust);
    check_hresult(result);
}

JsonObject identity() {
    auto current = Package::Current();
    auto id = current.Id();
    JsonObject result;
    text(result, L"name", id.Name());
    text(result, L"publisher", id.Publisher());
    text(result, L"family", id.FamilyName());
    text(result, L"full_name", id.FullName());
    text(result, L"version", version(id.Version()));
    text(result, L"program_root", current.InstalledPath());
    PWSTR raw = nullptr;
    check_hresult(SHGetKnownFolderPath(FOLDERID_LocalAppData, KF_FLAG_DEFAULT, nullptr, &raw));
    std::wstring folder(raw);
    CoTaskMemFree(raw);
    text(result, L"local_app_data", folder);
    result.Insert(L"deployment_in_progress", JsonValue::CreateBooleanValue(current.Status().DeploymentInProgress()));
    return result;
}

// Verification is repeated immediately before deployment. Only a newer version
// of this package, with the same publisher and architecture, can be deployed.
JsonObject candidate(std::wstring const& path, bool allowCurrent = false) {
    verify(path);
    com_ptr<IStream> stream;
    check_hresult(SHCreateStreamOnFileEx(path.c_str(), STGM_READ | STGM_SHARE_DENY_WRITE,
        FILE_ATTRIBUTE_NORMAL, FALSE, nullptr, stream.put()));
    com_ptr<IAppxFactory> factory;
    check_hresult(CoCreateInstance(CLSID_AppxFactory, nullptr, CLSCTX_INPROC_SERVER,
        __uuidof(IAppxFactory), factory.put_void()));
    com_ptr<IAppxPackageReader> reader;
    check_hresult(factory->CreatePackageReader(stream.get(), reader.put()));
    com_ptr<IAppxManifestReader> manifest;
    check_hresult(reader->GetManifest(manifest.put()));
    com_ptr<IAppxManifestPackageId> id;
    check_hresult(manifest->GetPackageId(id.put()));
    LPWSTR rawName = nullptr, rawPublisher = nullptr;
    check_hresult(id->GetName(&rawName));
    std::wstring name(rawName);
    CoTaskMemFree(rawName);
    check_hresult(id->GetPublisher(&rawPublisher));
    std::wstring publisher(rawPublisher);
    CoTaskMemFree(rawPublisher);
    UINT64 number = 0;
    APPX_PACKAGE_ARCHITECTURE architecture;
    check_hresult(id->GetVersion(&number));
    check_hresult(id->GetArchitecture(&architecture));
    auto current = Package::Current().Id();
    auto currentVersion = current.Version();
    UINT64 currentNumber = (UINT64(currentVersion.Major) << 48) |
        (UINT64(currentVersion.Minor) << 32) | (UINT64(currentVersion.Build) << 16) | currentVersion.Revision;
    if (name != current.Name() || publisher != current.Publisher() ||
        architecture != APPX_PACKAGE_ARCHITECTURE_X64 || number < currentNumber || (!allowCurrent && number == currentNumber)) {
        throw hresult_invalid_argument(L"MSIX-CANDIDATE-IDENTITY-OR-VERSION");
    }
    com_ptr<IAppxFile> contractFile;
    check_hresult(reader->GetPayloadFile(L"bundle.json", contractFile.put()));
    UINT64 contractSize = 0;
    check_hresult(contractFile->GetSize(&contractSize));
    if (contractSize > 4 * 1024 * 1024) throw hresult_invalid_argument(L"MSIX-CONTRACT-SIZE");
    com_ptr<IStream> contractStream;
    check_hresult(contractFile->GetStream(contractStream.put()));
    std::string contract(static_cast<size_t>(contractSize), '\0');
    ULONG read = 0;
    check_hresult(contractStream->Read(contract.data(), static_cast<ULONG>(contractSize), &read));
    if (read != contractSize) throw hresult_invalid_argument(L"MSIX-CONTRACT-READ");
    auto database = JsonObject::Parse(to_hstring(contract)).GetNamedObject(L"database");
    std::ifstream currentFile(std::filesystem::path(Package::Current().InstalledPath().c_str()) / L"bundle.json", std::ios::binary);
    if (!currentFile) throw hresult_invalid_argument(L"MSIX-CURRENT-CONTRACT");
    std::string currentContract((std::istreambuf_iterator<char>(currentFile)), std::istreambuf_iterator<char>());
    auto currentDatabase = JsonObject::Parse(to_hstring(currentContract)).GetNamedObject(L"database");
    for (auto field : {L"postgresql", L"vector", L"pg_trgm", L"schema_digest", L"role_policy_digest"}) {
        if (database.GetNamedString(field) != currentDatabase.GetNamedString(field)) {
            throw hresult_invalid_argument(L"MSIX-DATABASE-INCOMPATIBLE");
        }
    }
    PackageVersion target{UINT16(number >> 48), UINT16(number >> 32), UINT16(number >> 16), UINT16(number)};
    JsonObject result;
    text(result, L"name", name);
    text(result, L"publisher", publisher);
    text(result, L"version", version(target));
    result.Insert(L"database", database);
    result.Insert(L"already_installed", JsonValue::CreateBooleanValue(number == currentNumber));
    return result;
}
}

// 0 identity, 1 inspect trusted candidate, 2 defer own update,
// 3 startup status, 4 request startup, 5 disable startup,
// 6 activate environment host, 7 create supervised host child, 8 stop idle host,
// 9 restart update, 10 request own uninstall (explicit delete or preserve).
extern "C" __declspec(dllexport) HRESULT __stdcall armi_windows_call(
    UINT32 operation, wchar_t const* argument, wchar_t* output, UINT32 capacity) noexcept {
    try {
        Apartment apartment;
        if (!output || !capacity) return E_INVALIDARG;
        JsonObject result;
        switch (operation) {
        case 0:
            result = identity();
            break;
        case 1:
        case 2: {
            if (!argument || !std::filesystem::path(argument).is_absolute()) return E_INVALIDARG;
            result = candidate(argument);
            if (operation == 2) {
                using namespace Windows::Management::Deployment;
                AddPackageOptions options;
                options.DeferRegistrationWhenPackagesAreInUse(true);
                wchar_t uri[32768];
                DWORD uriLength = ARRAYSIZE(uri);
                check_hresult(UrlCreateFromPathW(argument, uri, &uriLength, 0));
                auto deployed = PackageManager().AddPackageByUriAsync(
                    Windows::Foundation::Uri(uri), options).get();
                check_hresult(deployed.ExtendedErrorCode());
                text(result, L"status", L"registration_deferred");
            }
            break;
        }
        case 3:
        case 4:
        case 5: {
            auto task = StartupTask::GetAsync(L"ARMIStartup").get();
            if (operation == 4 && task.State() == StartupTaskState::Disabled) {
                task.RequestEnableAsync().get();
            } else if (operation == 5 && task.State() == StartupTaskState::Enabled) {
                task.Disable();
            }
            result.Insert(L"state", JsonValue::CreateNumberValue(static_cast<int>(task.State())));
            break;
        }
        case 6:
            if (!argument) return E_INVALIDARG;
            activate_host(argument);
            text(result, L"status", L"ready");
            break;
        case 7:
            if (!argument) return E_INVALIDARG;
            result = spawn_child(JsonObject::Parse(argument));
            break;
        case 8: {
            if (!argument) return E_INVALIDARG;
            auto name = job_name(argument);
            HANDLE raw = OpenJobObjectW(JOB_OBJECT_QUERY, FALSE, name.c_str());
            if (raw) {
                Handle job(raw);
                JOBOBJECT_BASIC_ACCOUNTING_INFORMATION state{};
                check_bool(QueryInformationJobObject(job.value, JobObjectBasicAccountingInformation, &state, sizeof(state), nullptr));
                if (state.ActiveProcesses) return HRESULT_FROM_WIN32(ERROR_BUSY);
                Handle stop(OpenEventW(EVENT_MODIFY_STATE, FALSE, (name + L".stop").c_str()));
                check_bool(SetEvent(stop.value));
                auto deadline = GetTickCount64() + 5000;
                while (host_ready(name)) {
                    if (GetTickCount64() >= deadline) return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
                    Sleep(20);
                }
            }
            text(result, L"status", L"stopped");
            break;
        }
        case 9: {
            if (!argument) return E_INVALIDARG;
            result = candidate(argument);
            if (std::wstring_view(argument).find(L'"') != std::wstring_view::npos) return E_INVALIDARG;
            com_ptr<IApplicationActivationManager> activation;
            check_hresult(CoCreateInstance(CLSID_ApplicationActivationManager, nullptr, CLSCTX_LOCAL_SERVER,
                __uuidof(IApplicationActivationManager), activation.put_void()));
            auto app = std::wstring(Package::Current().Id().FamilyName()) + L"!ARMI";
            auto arguments = L"--apply-update \"" + std::wstring(argument) + L"\"";
            DWORD pid;
            check_hresult(activation->ActivateApplication(app.c_str(), arguments.c_str(), AO_NOERRORUI, &pid));
            text(result, L"status", L"deployment_requested");
            break;
        }
        case 10: {
            if (!argument || (std::wstring_view(argument) != L"delete" && std::wstring_view(argument) != L"preserve")) return E_INVALIDARG;
            require_idle_environments();
            if (std::wstring_view(argument) == L"delete") require_plain_data_tree(package_data_root());
            com_ptr<IApplicationActivationManager> activation;
            check_hresult(CoCreateInstance(CLSID_ApplicationActivationManager, nullptr, CLSCTX_LOCAL_SERVER,
                __uuidof(IApplicationActivationManager), activation.put_void()));
            auto app = std::wstring(Package::Current().Id().FamilyName()) + L"!ARMI";
            auto arguments = L"--uninstall-package " + std::wstring(argument) + L":" + std::to_wstring(GetCurrentProcessId());
            DWORD pid;
            check_hresult(activation->ActivateApplication(app.c_str(), arguments.c_str(), AO_NOERRORUI, &pid));
            text(result, L"status", L"uninstall_requested");
            result.Insert(L"delete_data", JsonValue::CreateBooleanValue(std::wstring_view(argument) == L"delete"));
            break;
        }
        default:
            return E_INVALIDARG;
        }
        auto serialized = result.Stringify();
        if (serialized.size() >= capacity) return HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER);
        wcscpy_s(output, capacity, serialized.c_str());
        return S_OK;
    } catch (hresult_error const& error) {
        if (output && capacity && error.message().size() < capacity) {
            wcscpy_s(output, capacity, error.message().c_str());
        }
        return error.code();
    } catch (...) {
        return to_hresult();
    }
}

extern "C" __declspec(dllexport) HRESULT __stdcall armi_uninstall_package(wchar_t const* argument) noexcept {
    bool cleaning = false;
    try {
        Apartment apartment;
        if (!argument) return E_INVALIDARG;
        std::wstring request(argument);
        auto separator = request.find(L':');
        auto mode = request.substr(0, separator);
        if (separator == std::wstring::npos || (mode != L"delete" && mode != L"preserve")) return E_INVALIDARG;
        auto caller = request.substr(separator + 1);
        if (caller.empty() || caller.find_first_not_of(L"0123456789") != std::wstring::npos) return E_INVALIDARG;
        auto pid = std::stoul(caller);
        if (!pid || pid == GetCurrentProcessId()) return E_INVALIDARG;
        // Let the CLI emit its receipt, or the desktop release its lock and exit.
        // A persistent MCP client is closed with the other package clients below.
        HANDLE raw = OpenProcess(SYNCHRONIZE, FALSE, pid);
        if (raw) { Handle process(raw); WaitForSingleObject(process.value, 10000); }
        DeploymentGate gate;
        auto eventName = L"Local\\" + std::wstring(Package::Current().Id().FamilyName()) + L".uninstalling";
        Handle removing(CreateEventW(nullptr, TRUE, TRUE, eventName.c_str()));
        if (GetLastError() == ERROR_ALREADY_EXISTS) return HRESULT_FROM_WIN32(ERROR_BUSY);
        require_idle_environments();
        auto root = package_data_root();
        if (mode == L"delete") require_plain_data_tree(root);
        close_package_clients();
        if (mode == L"delete") {
            require_plain_data_tree(root);
            cleaning = true;
            std::filesystem::remove_all(root);
        }
        // Windows owns package registration and files. This process may be
        // terminated by deployment; requested is never reported as completed.
        using namespace Windows::Management::Deployment;
        auto result = PackageManager().RemovePackageAsync(Package::Current().Id().FullName()).get();
        check_hresult(result.ExtendedErrorCode());
        return S_OK;
    } catch (...) {
        auto result = to_hresult();
        wchar_t message[512];
        swprintf_s(message, L"ARMI uninstall failed (0x%08X). %s", static_cast<unsigned int>(result),
            cleaning ? L"Data cleanup may have completed partially or fully. The package may still be installed." : L"Data cleanup was not started. The package may still be installed.");
        MessageBoxW(nullptr, message, L"ARMI", MB_OK | MB_ICONERROR);
        return result;
    }
}

extern "C" __declspec(dllexport) HRESULT __stdcall armi_restart_update(wchar_t const* path) noexcept {
    try {
        Apartment apartment;
        if (!path) return E_INVALIDARG;
        auto verified = candidate(path, true);
        if (verified.GetNamedBoolean(L"already_installed")) return S_FALSE;
        DeploymentGate gate;
        require_idle_environments();
        check_hresult(RegisterApplicationRestart(L"--background", 0));
        using namespace Windows::Management::Deployment;
        AddPackageOptions options;
        options.ForceTargetAppShutdown(true);
        wchar_t uri[32768];
        DWORD length = ARRAYSIZE(uri);
        check_hresult(UrlCreateFromPathW(path, uri, &length, 0));
        auto result = PackageManager().AddPackageByUriAsync(Windows::Foundation::Uri(uri), options).get();
        check_hresult(result.ExtendedErrorCode());
        return S_OK;
    } catch (...) { return to_hresult(); }
}

extern "C" __declspec(dllexport) HRESULT __stdcall armi_environment_host(wchar_t const* environment) noexcept {
    try {
        Apartment apartment;
        if (!environment) return E_INVALIDARG;
        auto name = job_name(environment);
        Handle singleton(CreateMutexW(nullptr, FALSE, (name + L".host").c_str()));
        if (GetLastError() == ERROR_ALREADY_EXISTS) return S_OK;
        Handle stop(CreateEventW(nullptr, TRUE, FALSE, (name + L".stop").c_str()));
        Handle ready(CreateEventW(nullptr, TRUE, FALSE, (name + L".ready").c_str()));
        Handle job(CreateJobObjectW(nullptr, name.c_str()));
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        check_bool(SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &limits, sizeof(limits)));
        WNDCLASSW windowClass{};
        windowClass.lpfnWndProc = host_window;
        windowClass.hInstance = GetModuleHandleW(nullptr);
        windowClass.lpszClassName = L"ArmiEnvironmentHost";
        check_bool(RegisterClassW(&windowClass));
        HWND window = CreateWindowExW(0, windowClass.lpszClassName, environment, 0,
            0, 0, 0, 0, nullptr, nullptr, windowClass.hInstance, nullptr);
        check_bool(window != nullptr);
        check_bool(SetEvent(ready.value));
        for (;;) {
            DWORD event = MsgWaitForMultipleObjects(1, &stop.value, FALSE, INFINITE, QS_ALLINPUT);
            if (event == WAIT_OBJECT_0) break;
            if (event == WAIT_FAILED) throw_last_error();
            MSG message;
            while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
                if (message.message == WM_QUIT) { DestroyWindow(window); return S_OK; }
                TranslateMessage(&message);
                DispatchMessageW(&message);
            }
        }
        DestroyWindow(window);
        return S_OK;
    } catch (...) { return to_hresult(); }
}
