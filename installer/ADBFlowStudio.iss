; Inno Setup 6 script for ADB Flow Studio.
; Build the desktop and helper executables first with desktop\build_windows.bat.

#define AppName "ADB Flow Studio"
#define AppVersion "0.1.0"
#define AppPublisher "ADB Flow Studio"
#define AppExeName "ADBFlowStudio.exe"

[Setup]
AppId={{E5BBD9F0-4E6A-4C82-8D4A-7C43A1D03B16}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/mahirlabib478-del/automation-ui
DefaultDirName={localappdata}\Programs\ADB Flow Studio
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputBaseFilename=ADBFlowStudioSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
Uninstallable=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\ADBFlowStudio.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\adb-flow-studio-recorder.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\adb-flow-studio-replayer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "Customer-Quick-Start.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch ADB Flow Studio"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent
