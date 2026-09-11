// Acceptance-only executable: exercises real Windows deployment before integration.
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shlobj.h>
#include <winrt/Windows.ApplicationModel.h>
#include <winrt/Windows.Management.Deployment.h>
#include <winrt/Windows.Foundation.h>
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
        if (argc == 3 && std::wstring_view(argv[1]) == L"--environment-host") {
            auto libraryPath = executable.parent_path() / L"armi_windows.dll";
            HMODULE library = LoadLibraryW(libraryPath.c_str());
            if (!library) throw winrt::hresult_error(HRESULT_FROM_WIN32(GetLastError()));
            using Host = HRESULT(__stdcall*)(wchar_t const*);
            auto host = reinterpret_cast<Host>(GetProcAddress(library, "armi_environment_host"));
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
            STARTUPINFOW startup{sizeof(startup)};
            PROCESS_INFORMATION child{};
            winrt::check_bool(CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW | CREATE_SUSPENDED, nullptr, nullptr, &startup, &child));
            std::wstring request = L"{\"environment_id\":\"" + std::wstring(argv[2]) + L"\",\"pid\":" + std::to_wstring(child.dwProcessId) + L"}";
            HRESULT result = call(7, request.c_str(), output, ARRAYSIZE(output));
            if (FAILED(result)) TerminateProcess(child.hProcess, 2);
            CloseHandle(child.hThread);
            CloseHandle(child.hProcess);
            FreeLibrary(library);
            winrt::check_hresult(result);
            std::wcout << L"child-pid=" << child.dwProcessId << std::endl;
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
