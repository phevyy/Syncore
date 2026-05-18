[Setup]
AppName=Syncore
AppVersion=1.0.0
AppPublisher=Syncore
DefaultDirName={autopf}\Syncore
DefaultGroupName=Syncore
OutputDir=installer
OutputBaseFilename=SyncoreSetup
SetupIconFile=assets\icon\logo.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
UninstallDisplayIcon={app}\Syncore.exe
DisableProgramGroupPage=yes
LicenseFile=
InfoBeforeFile=

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "Masaüstüne kısayol oluştur"; GroupDescription: "Ek görevler:"; Flags: checkedonce

[Files]
Source: "dist\Syncore\Syncore.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Syncore\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Syncore"; Filename: "{app}\Syncore.exe"; IconFilename: "{app}\Syncore.exe"
Name: "{autodesktop}\Syncore"; Filename: "{app}\Syncore.exe"; IconFilename: "{app}\Syncore.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Syncore.exe"; Description: "Syncore'u başlat"; Flags: nowait postinstall skipifsilent
