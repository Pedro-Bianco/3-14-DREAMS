; PI dreams installer — Inno Setup 6. Build it with installer\build.ps1.

#define AppVersion "0.9.0"
; Ollama older than this gets updated. Set by measurement
; (first version with Vulkan on by default).
#define MinOllama "0.40.6"
#define OllamaUninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\{44E83376-CE68-45EB-8FC1-393500EB558C}_is1"

[Setup]
AppId={{6E1B4C2A-2F1D-4D7C-9B0E-5A1C3F7D8E91}
AppName=PI dreams
AppVersion={#AppVersion}
AppPublisher=PI dreams
DefaultDirName={localappdata}\Programs\PI dreams
DefaultGroupName=PI dreams
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=Output
OutputBaseFilename=PIDreams-Setup-{#AppVersion}
SetupIconFile=assets\pidreams.ico
UninstallDisplayIcon={app}\PIDreams.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Closes/waits for the running app (mutex created by pidreams/core/single_instance.py).
AppMutex=PIDreams

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; Flags: unchecked

[Files]
Source: "..\dist\PIDreams\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Licenses: the installer bundles eSpeak NG and phonemizer (GPL-3.0) — see THIRD_PARTY_NOTICES.md
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSES\*"; DestDir: "{app}\LICENSES"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\PI dreams"; Filename: "{app}\PIDreams.exe"
Name: "{autodesktop}\PI dreams"; Filename: "{app}\PIDreams.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PIDreams.exe"; Parameters: "--setup-models"; StatusMsg: "Baixando os modelos de IA (pode levar alguns minutos)..."; Flags: waituntilterminated
Filename: "{app}\PIDreams.exe"; Description: "Abrir o PI dreams"; Flags: postinstall nowait skipifsilent

[Code]
type
  TMemoryStatusEx = record
    dwLength: Cardinal;
    dwMemoryLoad: Cardinal;
    ullTotalPhys: Int64;
    ullAvailPhys: Int64;
    ullTotalPageFile: Int64;
    ullAvailPageFile: Int64;
    ullTotalVirtual: Int64;
    ullAvailVirtual: Int64;
    ullAvailExtendedVirtual: Int64;
  end;

function GlobalMemoryStatusEx(var Status: TMemoryStatusEx): Boolean;
  external 'GlobalMemoryStatusEx@kernel32.dll stdcall';

const
  GiB = 1073741824;
  // 16 GB of physical memory show up as ~15.8 GiB usable.
  MinRamGiB = 15;
  MinDiskGiB = 15;

var
  DownloadPage: TDownloadWizardPage;

function RamTotalGiB: Integer;
var
  Status: TMemoryStatusEx;
begin
  Status.dwLength := SizeOf(Status);
  if GlobalMemoryStatusEx(Status) then
    Result := Status.ullTotalPhys div GiB
  else
    Result := 0;
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if RamTotalGiB < MinRamGiB then
  begin
    MsgBox('O PI dreams precisa de pelo menos 16 GB de memória RAM.' + #13#10 +
           'Este computador tem ' + IntToStr(RamTotalGiB) + ' GB.' + #13#10#13#10 +
           'A instalação não pode continuar.', mbCriticalError, MB_OK);
    Result := False;
  end;
end;

// Next number of an "a.b.c" version; consumes the text it reads.
function NextNumber(var Version: String): Integer;
var
  Dot: Integer;
begin
  Dot := Pos('.', Version);
  if Dot = 0 then
  begin
    Result := StrToIntDef(Version, 0);
    Version := '';
  end
  else
  begin
    Result := StrToIntDef(Copy(Version, 1, Dot - 1), 0);
    Delete(Version, 1, Dot);
  end;
end;

function VersionLess(A, B: String): Boolean;
var
  I, X, Y: Integer;
begin
  Result := False;
  for I := 1 to 3 do
  begin
    X := NextNumber(A);
    Y := NextNumber(B);
    if X <> Y then
    begin
      Result := X < Y;
      Exit;
    end;
  end;
end;

function OllamaNeedsInstall: Boolean;
var
  Version: String;
begin
  if not RegQueryStringValue(HKCU, '{#OllamaUninstallKey}', 'DisplayVersion', Version) then
    Result := True
  else
    Result := VersionLess(Version, '{#MinOllama}');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Free, Total: Int64;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    if GetSpaceOnDisk64(ExtractFileDrive(WizardDirValue), Free, Total) and
       (Free < Int64(MinDiskGiB) * GiB) then
    begin
      MsgBox('São necessários pelo menos 15 GB livres em ' + ExtractFileDrive(WizardDirValue) +
             ' (há ' + IntToStr(Free div GiB) + ' GB).' + #13#10 +
             'Libere espaço ou escolha outra unidade.', mbError, MB_OK);
      Result := False;
    end;
  end
  else if (CurPageID = wpReady) and OllamaNeedsInstall then
  begin
    DownloadPage.Clear;
    DownloadPage.Add('https://ollama.com/download/OllamaSetup.exe', 'OllamaSetup.exe', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
      except
        MsgBox('Não foi possível baixar o Ollama: ' + GetExceptionMessage + #13#10 +
               'Verifique a internet e tente de novo.', mbError, MB_OK);
        Result := False;
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Baixando o Ollama',
    'O Ollama roda os modelos de IA no seu computador.', nil);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
begin
  if (CurStep = ssInstall) and FileExists(ExpandConstant('{tmp}\OllamaSetup.exe')) then
  begin
    WizardForm.StatusLabel.Caption := 'Instalando o Ollama...';
    if not Exec(ExpandConstant('{tmp}\OllamaSetup.exe'), '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
                '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
      MsgBox('A instalação do Ollama não terminou (código ' + IntToStr(ExitCode) + ').' + #13#10 +
             'Você pode instalá-lo depois em https://ollama.com/download', mbError, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\PIDreams');
    if DirExists(DataDir) and
       (MsgBox('Apagar também suas configurações, memória e modelos baixados?' + #13#10 + DataDir,
               mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(DataDir, True, True, True);
  end;
end;
