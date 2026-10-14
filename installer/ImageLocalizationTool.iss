; Image Localization Tool Windows installer (Inno Setup 6.1 or newer).
; Stage: dist/ImageLocalizationTool (desktop/, sidecar/, web, fonts, models).
; The app entry is the Flutter host at desktop\ImageLocalizationTool.exe;
; the Python sidecar lives in sidecar\. Version is not stored here.
; scripts/build-windows.ps1 passes /DAppVersion read from src/app/__init__.py.
; No Edge runtime is downloaded: the shipped shell renders with Flutter,
; and --api never imports pywebview. PrivilegesRequired=lowest installs per user.

#ifndef AppVersion
  #error Pass /DAppVersion from scripts/build-windows.ps1 (src/app/__init__.py).
#endif
#ifndef DistDir
  #define DistDir "..\dist\ImageLocalizationTool"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define MyAppName "Image Localization Tool"
#define MyAppExeName "ImageLocalizationTool.exe"
#define MyAppEntry "desktop\ImageLocalizationTool.exe"

[Setup]
AppId={{8F3C1A72-4E59-4B16-9D80-2C6A7F51E0B4}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=ImageLocalizationTool-{#AppVersion}-windows-x64-setup
UninstallDisplayIcon={app}\{#MyAppEntry}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
CloseApplications=force

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; runtime/ (компоненты torch/Argos) и data/ в установщик не входят:
; паки качаются из программы, data/ — признак портативной раскладки.
Source: "{#DistDir}\*"; DestDir: "{app}"; Excludes: "runtime,data,models,.downloads,.resources,.builtin,.installer.lock,preparation.json"; Flags: ignoreversion recursesubdirs createallsubdirs

; Upgrade over the pywebview layout: drop the old root exe and its bundle.
[InstallDelete]
Type: files; Name: "{app}\ImageLocalizationTool.exe"
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppEntry}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppEntry}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppEntry}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
