"""Generate MSIX metadata from the release configuration and sealed payload."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

FOUNDATION = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
NAMESPACES = {
    "": FOUNDATION,
    "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
    "uap5": "http://schemas.microsoft.com/appx/manifest/uap/windows10/5",
    "uap10": "http://schemas.microsoft.com/appx/manifest/uap/windows10/10",
    "desktop": "http://schemas.microsoft.com/appx/manifest/desktop/windows10",
    "desktop4": "http://schemas.microsoft.com/appx/manifest/desktop/windows10/4",
    "rescap": FOUNDATION + "/restrictedcapabilities",
    "virtualization": "http://schemas.microsoft.com/appx/manifest/virtualization/windows10",
}


def prepare(
    root: Path,
    config: Path,
    publisher: str,
    development: bool,
    isolated_acceptance: bool = False,
) -> None:
    release = yaml.safe_load(config.read_text(encoding="utf-8"))
    fields = {
        "schema_kind",
        "name",
        "publisher",
        "publisher_display_name",
        "version",
        "data_directory",
        "execution_alias",
        "repository",
        "release_tag",
    }
    if not isinstance(release, dict) or set(release) != fields:
        raise ValueError("MSIX-RELEASE-CONFIG-FIELDS")
    if release["schema_kind"] != "armi.windows-release":
        raise ValueError("MSIX-RELEASE-CONFIG-VERSION")
    if isolated_acceptance and not development:
        raise ValueError("MSIX-ISOLATED-ACCEPTANCE-REQUIRES-DEVELOPMENT")
    if development:
        release.update(
            name="YifeiLi99.ARMI.MsixAcceptance"
            if isolated_acceptance
            else "YifeiLi99.ARMI.Acceptance",
            publisher=publisher,
            data_directory="ARMI.MsixAcceptance"
            if isolated_acceptance
            else "ARMI.Acceptance",
            execution_alias="ARMI.MsixAcceptance.exe"
            if isolated_acceptance
            else "ARMI.Acceptance.exe",
        )
    elif (
        release["name"] != "YifeiLi99.ARMI"
        or release["data_directory"] != "ARMI"
        or release["execution_alias"] != "ARMI.exe"
    ):
        raise ValueError("MSIX-PRODUCTION-IDENTITY")
    if not release["publisher"] or release["publisher"] != publisher:
        raise ValueError("MSIX-PUBLISHER-CERTIFICATE-MISMATCH")
    version = release["version"]
    if (
        not isinstance(version, str)
        or re.fullmatch(
            r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)",
            version,
        )
        is None
        or any(int(part) > 65535 for part in version.split("."))
    ):
        raise ValueError("MSIX-FOUR-PART-VERSION")
    if (
        release["repository"] != "YifeiLi99/ARMI"
        or not isinstance(release["release_tag"], str)
        or re.fullmatch(r"[A-Za-z0-9._-]+", release["release_tag"]) is None
    ):
        raise ValueError("MSIX-UPDATE-ORIGIN")
    for prefix, uri in NAMESPACES.items():
        ET.register_namespace(prefix, uri)

    def node(
        parent: ET.Element, tag: str, text: str | None = None, **attrs: str
    ) -> ET.Element:
        prefix, _, local = tag.partition(":")
        uri = NAMESPACES[prefix] if local else FOUNDATION
        element = ET.SubElement(parent, f"{{{uri}}}{local or prefix}", attrs)
        element.text = text
        return element

    package = ET.Element(
        f"{{{FOUNDATION}}}Package",
        IgnorableNamespaces="uap uap5 uap10 desktop desktop4 rescap virtualization",
    )
    node(
        package,
        "Identity",
        Name=release["name"],
        Publisher=release["publisher"],
        Version=version,
        ProcessorArchitecture="x64",
    )
    properties = node(package, "Properties")
    display_name = "ARMI"
    node(properties, "DisplayName", display_name)
    node(properties, "PublisherDisplayName", release["publisher_display_name"])
    node(properties, "Logo", "Assets/StoreLogo.png")
    virtualization = node(properties, "virtualization:FileSystemWriteVirtualization")
    exclusions = node(virtualization, "virtualization:ExcludedDirectories")
    node(
        exclusions,
        "virtualization:ExcludedDirectory",
        "$(KnownFolder:LocalAppData)\\" + release["data_directory"],
    )
    dependencies = node(package, "Dependencies")
    node(
        dependencies,
        "TargetDeviceFamily",
        Name="Windows.Desktop",
        MinVersion="10.0.22000.0",
        MaxVersionTested="10.0.26100.0",
    )
    node(node(package, "Resources"), "Resource", Language="zh-CN")
    application = node(
        node(package, "Applications"),
        "Application",
        Id="ARMI",
        Executable="ARMI.exe",
        EntryPoint="Windows.FullTrustApplication",
        **{f"{{{NAMESPACES['desktop4']}}}SupportsMultipleInstances": "true"},
    )
    node(
        application,
        "uap:VisualElements",
        DisplayName=display_name,
        Description="ARMI",
        BackgroundColor="transparent",
        Square150x150Logo="Assets/Square150x150Logo.png",
        Square44x44Logo="Assets/Square44x44Logo.png",
    )
    extensions = node(application, "Extensions")
    # PostgreSQL's native tools re-execute the server through a system command
    # process. Register that existing internal executable with the same app;
    # it has no start-menu entry or execution alias of its own.
    database_process = node(
        extensions,
        "desktop:Extension",
        Category="windows.fullTrustProcess",
        Executable="postgresql/pgsql/bin/postgres.exe",
        EntryPoint="Windows.FullTrustApplication",
    )
    node(database_process, "desktop:FullTrustProcess")
    alias = node(
        extensions,
        "uap5:Extension",
        Category="windows.appExecutionAlias",
        Executable="ARMI.exe",
        EntryPoint="Windows.FullTrustApplication",
    )
    aliases = node(
        alias,
        "uap5:AppExecutionAlias",
        **{f"{{{NAMESPACES['desktop4']}}}Subsystem": "console"},
    )
    node(aliases, "uap5:ExecutionAlias", Alias=release["execution_alias"])
    startup = node(
        extensions,
        "desktop:Extension",
        Category="windows.startupTask",
        Executable="ARMI.exe",
        EntryPoint="Windows.FullTrustApplication",
        **{f"{{{NAMESPACES['uap10']}}}Parameters": "--background"},
    )
    node(
        startup,
        "desktop:StartupTask",
        TaskId="ARMIStartup",
        Enabled="false",
        DisplayName=display_name,
    )
    capabilities = node(package, "Capabilities")
    node(capabilities, "rescap:Capability", Name="runFullTrust")
    node(capabilities, "rescap:Capability", Name="unvirtualizedResources")
    ET.indent(package, space="  ")
    ET.ElementTree(package).write(
        root / "AppxManifest.xml", encoding="utf-8", xml_declaration=True
    )
    resources = root / "resources"
    resources.mkdir(exist_ok=True)
    (resources / "windows-release.yaml").write_text(
        yaml.safe_dump(release, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "name": release["name"],
                "version": version,
                "repository": release["repository"],
                "release_tag": release["release_tag"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("publisher")
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--isolated-acceptance", action="store_true")
    args = parser.parse_args()
    prepare(
        args.root,
        args.config,
        args.publisher,
        args.development,
        args.isolated_acceptance,
    )
