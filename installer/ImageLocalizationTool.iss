; Image Localization Tool Windows installer (Inno Setup 6.1 or newer).
; Stage: dist/ImageLocalizationTool (exe, _internal, web, fonts, models).
; Version is not stored here. scripts/build-windows.ps1 passes /DAppVersion
; read from src/app/__init__.py.
; WebView2: if the Evergreen Runtime is missing, download the official
; bootstrapper (https://go.microsoft.com/fwlink/p/?LinkId=2124703) and run it.
; PrivilegesRequired=lowest, so the bootstrapper installs for the current user.

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
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
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
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function WebView2VersionOk(Version: String): Boolean;
var
  Rest: String;
  Part: String;
  Dot: Integer;
  I: Integer;
  Number: Integer;
  First: Boolean;
begin
  Result := False;
  Rest := Trim(Version);
  if Rest = '' then
    exit;
  First := True;
  while Rest <> '' do
  begin
    Dot := Pos('.', Rest);
    if Dot = 0 then
    begin
      Part := Rest;
      Rest := '';
    end
    else
    begin
      Part := Copy(Rest, 1, Dot - 1);
      Rest := Copy(Rest, Dot + 1, Length(Rest));
    end;
    if Part = '' then
      exit;
    Number := 0;
    for I := 1 to Length(Part) do
    begin
      if (Part[I] < '0') or (Part[I] > '9') then
        exit;
      Number := (Number * 10) + (Ord(Part[I]) - Ord('0'));
    end;
    if First and (Number <= 0) then
      exit;
    First := False;
    Result := True;
  end;
end;

function WebView2PvPresent(Root: Integer; SubKey: String): Boolean;
var
  Version: String;
begin
  Result := False;
  if not RegQueryStringValue(Root, SubKey, 'pv', Version) then
    exit;
  Result := WebView2VersionOk(Version);
end;

function IsWebView2Installed: Boolean;
var
  Guids: TArrayOfString;
  Roots: array of Integer;
  I, R: Integer;
begin
  { Same client ids as src/app/desktop.py. }
  Result := False;
  SetArrayLength(Guids, 4);
  Guids[0] := '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Guids[1] := '{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}';
  Guids[2] := '{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}';
  Guids[3] := '{65C35B14-6C1D-4122-AC46-7148CC9D6497}';
  SetArrayLength(Roots, 4);
  Roots[0] := HKLM;
  Roots[1] := HKCU;
  Roots[2] := HKLM64;
  Roots[3] := HKCU64;
  for R := 0 to GetArrayLength(Roots) - 1 do
  begin
    for I := 0 to GetArrayLength(Guids) - 1 do
    begin
      if WebView2PvPresent(Roots[R], 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + Guids[I]) then
      begin
        Result := True;
        exit;
      end;
      if WebView2PvPresent(Roots[R], 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + Guids[I]) then
      begin
        Result := True;
        exit;
      end;
    end;
  end;
end;

function OnWebView2DownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
  try
    WizardForm.StatusLabel.Caption := 'Downloading Microsoft Edge WebView2 Runtime...';
  except
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Installer: String;
begin
  Result := '';
  if IsWebView2Installed then
    exit;
  try
    DownloadTemporaryFile(
      'https://go.microsoft.com/fwlink/p/?LinkId=2124703',
      'MicrosoftEdgeWebview2Setup.exe',
      '',
      @OnWebView2DownloadProgress);
  except
    Result := 'Could not download the Microsoft Edge WebView2 Evergreen bootstrapper.';
    exit;
  end;
  Installer := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
  if not Exec(Installer, '/silent /install', '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) then
  begin
    Result := 'Could not start the WebView2 Evergreen bootstrapper.';
    exit;
  end;
  if ResultCode = 3010 then
    NeedsRestart := True;
  if IsWebView2Installed then
    exit;
  if (ResultCode <> 0) and (ResultCode <> 3010) then
  begin
    Result := 'WebView2 Evergreen bootstrapper exited with code ' + IntToStr(ResultCode) + '.';
    exit;
  end;
  Result := 'Microsoft Edge WebView2 Runtime is still missing after the bootstrapper finished.';
end;
