#define AppVersion "1.0.1"
#ifndef DistDir
  #define DistDir SourcePath + "..\dist\AutoDeliver"
#endif
#ifndef ReleaseDir
  #define ReleaseDir SourcePath + "..\release"
#endif

[Setup]
AppId={{2C1D19CA-A9C6-42D9-A8B9-2EBB65852FE5}
AppName=AutoDeliver 求职工作台
AppVersion={#AppVersion}
AppPublisher=Gnahz
AppPublisherURL=https://github.com/875931932
AppSupportURL=https://gitee.com/yan-ace/automated-delivery/issues
AppUpdatesURL=https://gitee.com/yan-ace/automated-delivery
InfoBeforeFile=..\DISCLAIMER.md
DefaultDirName={localappdata}\Programs\AutoDeliver
DefaultGroupName=AutoDeliver 求职工作台
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.18362
OutputDir={#ReleaseDir}
OutputBaseFilename=AutoDeliver-Setup-{#AppVersion}-win64
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\AutoDeliver.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=AutoDeliver.exe,auto_deliver_worker.exe
RestartApplications=no
SetupLogging=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName=AutoDeliver
VersionInfoCompany=Gnahz

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AutoDeliver 求职工作台"; Filename: "{app}\AutoDeliver.exe"; WorkingDir: "{app}"
Name: "{group}\卸载 AutoDeliver"; Filename: "{uninstallexe}"
Name: "{group}\项目主页"; Filename: "https://gitee.com/yan-ace/automated-delivery"
Name: "{autodesktop}\AutoDeliver 求职工作台"; Filename: "{app}\AutoDeliver.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AutoDeliver.exe"; Description: "启动 AutoDeliver 求职工作台"; Flags: nowait postinstall skipifsilent
