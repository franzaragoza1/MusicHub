; MusicHub - instalador para Windows (Inno Setup 6)
; Genera un unico "MusicHub-Windows-Setup.exe" que instala la app por usuario
; (sin pedir permisos de administrador) y crea accesos directos. Los archivos
; internos quedan ocultos dentro de la carpeta de instalacion.

#define MyAppName "MusicHub"
#define MyAppVersion "1.0.0"
#define MyAppExe "MusicHub.exe"

[Setup]
AppId={{B8E7A1C4-5D2F-4E9A-8B3C-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=MusicHub
DefaultDirName={localappdata}\Programs\MusicHub
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=MusicHub-Windows-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExe}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "dist\MusicHub\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Abrir MusicHub ahora"; Flags: nowait postinstall skipifsilent
