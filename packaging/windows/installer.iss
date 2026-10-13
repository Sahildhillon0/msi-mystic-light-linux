; Inno Setup script: wraps dist\MSI Mystic Light\ into a single setup .exe.
; Per-user install, no administrator rights needed (HID access on Windows
; does not need them either).
;
;   iscc /DAppVersion=0.3.0 packaging\windows\installer.iss

#ifndef AppVersion
  #define AppVersion "0.3.0"
#endif

[Setup]
AppId={{6D3B1F0E-6A55-4C8B-9E0B-5F7B4B1C2D61}
AppName=MSI Mystic Light
AppVersion={#AppVersion}
AppPublisher=msi-mystic-light-linux
AppPublisherURL=https://github.com/Sahildhillon0/msi-mystic-light-linux
DefaultDirName={localappdata}\Programs\MSI Mystic Light
DefaultGroupName=MSI Mystic Light
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=MSI-Mystic-Light-Setup-{#AppVersion}
SetupIconFile=msirgb.ico
UninstallDisplayIcon={app}\MSI Mystic Light.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\MSI Mystic Light\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\MSI Mystic Light"; Filename: "{app}\MSI Mystic Light.exe"
Name: "{group}\Uninstall MSI Mystic Light"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MSI Mystic Light"; Filename: "{app}\MSI Mystic Light.exe"; Tasks: desktopicon

[Registry]
; The panel writes this value itself ("Restore lighting at login"); declared
; here only so uninstalling removes it.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "MSI Mystic Light"; ValueType: none; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\MSI Mystic Light.exe"; Description: "Open MSI Mystic Light"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop the background player so its files can be removed.
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ""MSI Mystic Light.exe"""; Flags: runhidden; RunOnceId: "StopPlayer"
