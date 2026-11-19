#define AppName "Puente Escáner"
#define AppVersion "0.2.0"
#define AppPublisher "DeviceBridge"
#define AppExeName "PuenteEscaner.exe"

[Setup]
AppId={{B95D0BA8-8943-44A2-AF83-1D738A9C0E4A}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\PuenteEscaner
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=..\dist\installer
OutputBaseFilename=PuenteEscaner-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\PuenteEscaner\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "config.yaml"; DestDir: "{commonappdata}\PuenteEscaner"; DestName: "config.yaml"; Flags: onlyifdoesntexist
Source: "prerequisites\dotnet-runtime-8.0.34-win-x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Dirs]
Name: "{commonappdata}\PuenteEscaner\Data"
Name: "{commonappdata}\PuenteEscaner\Data\tmp"

[Icons]
Name: "{commonstartup}\Puente Escáner"; Filename: "{app}\{#AppExeName}"; Parameters: "--config ""{commonappdata}\PuenteEscaner\config.yaml"""
Name: "{group}\Puente Escáner"; Filename: "{app}\{#AppExeName}"; Parameters: "--config ""{commonappdata}\PuenteEscaner\config.yaml"""

[Run]
Filename: "{tmp}\dotnet-runtime-8.0.34-win-x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando .NET Runtime 8…"; Flags: waituntilterminated; Check: NeedsDotNetRuntime
Filename: "{app}\{#AppExeName}"; Parameters: "--config ""{commonappdata}\PuenteEscaner\config.yaml"""; Description: "Iniciar Puente Escáner"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsDotNetRuntime(): Boolean;
var
  Versions: TArrayOfString;
  Index, DotPosition, MajorVersion: Integer;
begin
  Result := True;
  if RegGetSubkeyNames(HKLM64, 'SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.NETCore.App', Versions) then
  begin
    for Index := 0 to GetArrayLength(Versions) - 1 do
    begin
      DotPosition := Pos('.', Versions[Index]);
      if DotPosition > 1 then
      begin
        MajorVersion := StrToIntDef(Copy(Versions[Index], 1, DotPosition - 1), 0);
        if MajorVersion >= 8 then
        begin
          Result := False;
          Exit;
        end;
      end;
    end;
  end;
end;

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

; Deliberadamente no se elimina {commonappdata}\PuenteEscaner para preservar
; perfiles y trabajos locales si el usuario reinstala la aplicación.
