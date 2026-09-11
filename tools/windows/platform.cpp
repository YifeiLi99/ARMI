// Restricted ABI for the packaged Python application. No shell or arbitrary commands.
#define UNICODE
#define _UNICODE
#include <windows.h>
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
    ~Handle() { CloseHandle(value); }
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

void attach_child(JsonObject const& request) {
    DeploymentGate gate;
    auto name = job_name(std::wstring(request.GetNamedString(L"environment_id")));
    DWORD pid = static_cast<DWORD>(request.GetNamedNumber(L"pid"));
    Handle job(OpenJobObjectW(JOB_OBJECT_ASSIGN_PROCESS | JOB_OBJECT_QUERY, FALSE, name.c_str()));
    Handle process(OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid));
    // Runtime also owns optional executables downloaded into its data directory.
    // The caller may attach only its own newly suspended child, never another
    // application's process supplied by PID.
    Handle processes(CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0));
    PROCESSENTRY32W child{sizeof(child)};
    bool owned = false;
    if (Process32FirstW(processes.value, &child)) {
        do {
            if (child.th32ProcessID == pid) {
                owned = child.th32ParentProcessID == GetCurrentProcessId();
                break;
            }
        } while (Process32NextW(processes.value, &child));
    }
    if (!owned) throw hresult_access_denied(L"MSIX-HOST-CHILD-BOUNDARY");
    BOOL alreadyOwned = FALSE;
    check_bool(IsProcessInJob(process.value, job.value, &alreadyOwned));
    if (!alreadyOwned) check_bool(AssignProcessToJobObject(job.value, process.value));
    // Popen creates the child suspended. Resume its sole primary thread only
    // after job assignment, so no descendant can escape before supervision.
    Handle snapshot(CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0));
    THREADENTRY32 entry{sizeof(entry)};
    DWORD threadId = 0;
    if (Thread32First(snapshot.value, &entry)) {
        do {
            if (entry.th32OwnerProcessID == pid) {
                if (threadId) throw hresult_invalid_argument(L"MSIX-HOST-CHILD-NOT-SUSPENDED");
                threadId = entry.th32ThreadID;
            }
        } while (Thread32Next(snapshot.value, &entry));
    }
    if (!threadId) throw hresult_invalid_argument(L"MSIX-HOST-CHILD-EXITED");
    Handle thread(OpenThread(THREAD_SUSPEND_RESUME, FALSE, threadId));
    if (ResumeThread(thread.value) != 1) throw hresult_invalid_argument(L"MSIX-HOST-CHILD-SUSPEND-STATE");
}

void require_idle_environments() {
    auto name = std::wstring(Package::Current().Id().Name());
    if (name != L"YifeiLi99.ARMI" && name != L"YifeiLi99.ARMI.Acceptance") {
        throw hresult_invalid_argument(L"MSIX-UPDATE-PACKAGE-NAME");
    }
    PWSTR raw = nullptr;
    check_hresult(SHGetKnownFolderPath(FOLDERID_LocalAppData, KF_FLAG_DEFAULT, nullptr, &raw));
    auto root = std::filesystem::path(raw) / name.substr(10);
    CoTaskMemFree(raw);
    auto index = root / L"control/environments.yaml";
    if (!std::filesystem::exists(index)) return;
    auto registry = read_json(index);
    if (registry.GetNamedString(L"schema_version") != L"armi.installation-environments.v2") {
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
    for (auto field : {L"postgresql", L"vector", L"pg_trgm", L"baseline", L"schema_digest", L"role_policy_digest"}) {
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
// 6 activate environment host, 7 attach suspended packaged child, 8 stop idle host.
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
            attach_child(JsonObject::Parse(argument));
            text(result, L"status", L"attached");
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
        default:
            return E_INVALIDARG;
        }
        auto serialized = result.Stringify();
        if (serialized.size() >= capacity) return HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER);
        wcscpy_s(output, capacity, serialized.c_str());
        return S_OK;
    } catch (...) {
        return to_hresult();
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
        HWND window = CreateWindowExW(0, windowClass.lpszClassName, L"ARMI environment host", 0,
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
