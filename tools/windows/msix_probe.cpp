// Acceptance-only executable: exercises real Windows deployment before integration.
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shlobj.h>
#include <winrt/Windows.ApplicationModel.h>
#include <winrt/Windows.Management.Deployment.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Foundation.Collections.h>
#include <winrt/Windows.Data.Json.h>
#include <fstream>
#include <iostream>
#include <filesystem>

int wmain(int argc, wchar_t** argv) {
    try {
        if (argc == 2 && std::wstring_view(argv[1]) == L"repeat-native") {
            // Match Python's ABI use: there is no outer COM apartment to keep
            // WinRT DLLs alive after each call returns.
            wchar_t executable[32768];
            if (!GetModuleFileNameW(nullptr, executable, ARRAYSIZE(executable))) winrt::throw_last_error();
            auto path = std::filesystem::path(executable).parent_path() / L"armi_windows.dll";
            HMODULE library = LoadLibraryW(path.c_str());
            if (!library) winrt::throw_last_error();
            using Call = HRESULT(__stdcall*)(UINT32, wchar_t const*, wchar_t*, UINT32);
            auto call = reinterpret_cast<Call>(GetProcAddress(library, "armi_windows_call"));
            if (!call) return 2;
            wchar_t output[65536];
            for (int i = 0; i < 3; ++i) winrt::check_hresult(call(0, nullptr, output, ARRAYSIZE(output)));
            FreeLibrary(library);
            std::cout << "repeated-native-call-passed" << std::endl;
            return 0;
        }
        winrt::init_apartment();
        auto package = winrt::Windows::ApplicationModel::Package::Current();
        auto executable = std::filesystem::path(package.InstalledPath().c_str()) / L"ARMI.exe";
        if (argc == 3 && (std::wstring_view(argv[1]) == L"--environment-host" || std::wstring_view(argv[1]) == L"--uninstall-package")) {
            auto libraryPath = executable.parent_path() / L"armi_windows.dll";
            HMODULE library = LoadLibraryW(libraryPath.c_str());
            if (!library) throw winrt::hresult_error(HRESULT_FROM_WIN32(GetLastError()));
            using Host = HRESULT(__stdcall*)(wchar_t const*);
            auto host = reinterpret_cast<Host>(GetProcAddress(library,
                std::wstring_view(argv[1]) == L"--uninstall-package" ? "armi_uninstall_package" : "armi_environment_host"));
            if (!host) return 2;
            HRESULT result = host(argv[2]);
            FreeLibrary(library);
            winrt::check_hresult(result);
            return 0;
        }
        if (argc == 2 && std::wstring_view(argv[1]) == L"--child-tree") {
            std::wstring command = L"\"" + executable.wstring() + L"\" --child-sleep";
            STARTUPINFOW startup{sizeof(startup)};
            PROCESS_INFORMATION child{};
            winrt::check_bool(CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr, nullptr, &startup, &child));
            CloseHandle(child.hThread);
            CloseHandle(child.hProcess);
            Sleep(INFINITE);
        }
        if (argc == 2 && std::wstring_view(argv[1]) == L"--child-sleep") Sleep(INFINITE);
        if (argc == 3 && std::wstring_view(argv[1]) == L"host-child") {
            auto libraryPath = executable.parent_path() / L"armi_windows.dll";
            HMODULE library = LoadLibraryW(libraryPath.c_str());
            if (!library) throw winrt::hresult_error(HRESULT_FROM_WIN32(GetLastError()));
            using Call = HRESULT(__stdcall*)(UINT32, wchar_t const*, wchar_t*, UINT32);
            auto call = reinterpret_cast<Call>(GetProcAddress(library, "armi_windows_call"));
            if (!call) return 2;
            wchar_t output[65536];
            winrt::check_hresult(call(6, argv[2], output, ARRAYSIZE(output)));
            std::wstring command = L"\"" + executable.wstring() + L"\" --child-tree";
            using namespace winrt::Windows::Data::Json;
            JsonObject request;
            request.Insert(L"environment_id", JsonValue::CreateStringValue(argv[2]));
            request.Insert(L"executable", JsonValue::CreateStringValue(executable.wstring()));
            request.Insert(L"command", JsonValue::CreateStringValue(command));
            request.Insert(L"cwd", JsonValue::CreateStringValue(executable.parent_path().wstring()));
            request.Insert(L"creationflags", JsonValue::CreateNumberValue(CREATE_NO_WINDOW));
            JsonArray variables;
            auto block = GetEnvironmentStringsW();
            if (!block) winrt::throw_last_error();
            for (auto item = block; *item; item += wcslen(item) + 1) {
                variables.Append(JsonValue::CreateStringValue(item));
            }
            FreeEnvironmentStringsW(block);
            request.Insert(L"environment", variables);
            HANDLE nullHandle = CreateFileW(L"NUL", GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, 0, nullptr);
            if (nullHandle == INVALID_HANDLE_VALUE) winrt::throw_last_error();
            JsonArray handles;
            for (int i = 0; i < 3; ++i) handles.Append(JsonValue::CreateNumberValue(
                static_cast<double>(reinterpret_cast<UINT_PTR>(nullHandle))));
            request.Insert(L"handles", handles);
            HRESULT result = call(7, request.Stringify().c_str(), output, ARRAYSIZE(output));
            CloseHandle(nullHandle);
            FreeLibrary(library);
            winrt::check_hresult(result);
            auto child = JsonObject::Parse(output);
            CloseHandle(reinterpret_cast<HANDLE>(static_cast<UINT_PTR>(child.GetNamedNumber(L"handle"))));
            std::wcout << L"child-pid=" << static_cast<DWORD>(child.GetNamedNumber(L"pid")) << std::endl;
            return 0;
        }
        PWSTR folder = nullptr;
        winrt::check_hresult(SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &folder));
        auto data = std::filesystem::path(folder) / L"ARMI.MsixAcceptance";
        CoTaskMemFree(folder);
        std::filesystem::create_directories(data);
        auto version = package.Id().Version();
        std::ofstream marker(data / L"probe.txt");
        marker << version.Major << '.' << version.Minor << '.' << version.Build << '.' << version.Revision;
        marker.close();
        std::wcout << package.Id().FullName().c_str() << std::endl;
        if (argc >= 3 && std::wstring_view(argv[1]) == L"native") {
            auto libraryPath = std::filesystem::path(package.InstalledPath().c_str()) / L"armi_windows.dll";
            HMODULE library = LoadLibraryW(libraryPath.c_str());
            if (!library) throw winrt::hresult_error(HRESULT_FROM_WIN32(GetLastError()));
            using Call = HRESULT(__stdcall*)(UINT32, wchar_t const*, wchar_t*, UINT32);
            auto call = reinterpret_cast<Call>(GetProcAddress(library, "armi_windows_call"));
            if (!call) return 2;
            wchar_t output[65536];
            HRESULT result = call(static_cast<UINT32>(std::stoul(argv[2])), argc == 4 ? argv[3] : nullptr, output, ARRAYSIZE(output));
            FreeLibrary(library);
            winrt::check_hresult(result);
            std::wcout << output << std::endl;
        }
        if (argc == 3 && std::wstring_view(argv[1]) == L"defer") {
            using namespace winrt::Windows::Management::Deployment;
            AddPackageOptions options;
            options.DeferRegistrationWhenPackagesAreInUse(true);
            auto result = PackageManager().AddPackageByUriAsync(
                winrt::Windows::Foundation::Uri(argv[2]), options).get();
            winrt::check_hresult(result.ExtendedErrorCode());
            std::cout << "deployment-request-completed" << std::endl;
        }
        if (argc == 2 && std::wstring_view(argv[1]) == L"hold") {
            std::cin.get();
        }
        return 0;
    } catch (winrt::hresult_error const& error) {
        std::wcerr << error.message().c_str() << std::endl;
        return 1;
    }
}
