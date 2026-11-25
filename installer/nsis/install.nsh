; Install section body (ARCH-6, INST-REQ-030, 089). Creates exactly the items named in installer/footprint.json and nothing else:
; the program-data folder (locked by Winsys_FolderLock before anything is written into it, SL-13), the state file, in the github and gitlab modes the runner payload
; (program\runner.exe, SL-14) and the service (Winsys_CreateService), then the uninstaller and the uninstall entry last. Local only and an empty mode have no payload and no service.
; Runs only after elevation (the silent gate already ended the run otherwise).
; installer-state.json has the shape of installer/state.schema.json; the mode and the forge address are added by the runner step.
!ifndef INSTALLER_VERSION
  !define INSTALLER_VERSION "0.1.0"
!endif

Var InstallHandle

; The payload is a build input (installer.build --runner-payload defines RUNNER_PAYLOAD); it is never in Git. Without it a service mode refuses.
Function Install_Payload
  !ifdef RUNNER_PAYLOAD
    CreateDirectory "$APPDATA\EcosystemRunner\program"
    ClearErrors
    SetOverwrite try
    File "/oname=$APPDATA\EcosystemRunner\program\runner.exe" "${RUNNER_PAYLOAD}"
    IfErrors payload_failed
    Return
  !else
    Goto payload_failed
  !endif
  payload_failed:
  Push "payload"
  Push "File runner.exe"
  Push "1"
  Call LogStep
  Delete "$APPDATA\EcosystemRunner\program\runner.exe"
  SetErrorLevel 2
  Abort "The runner payload could not be written: installation stopped."
FunctionEnd

; The same names and content as installer/runners.py (MODE_FILE, FORGE_FILE): written after the state file and before the payload.
; The forge file exists only for a forge mode: a local or an empty mode has registered nothing. No address and no secret yet (SL-16, SL-17).
Function Install_RunnerState
  ${If} $runner_mode == ""
    Return
  ${EndIf}
  ${If} $runner_mode == "github"
  ${OrIf} $runner_mode == "gitlab"
    ClearErrors
    FileOpen $InstallHandle "$APPDATA\EcosystemRunner\runner-forge.json" w
    IfErrors forge_state_failed
    FileWrite $InstallHandle '{"forge": "$runner_mode"}$\r$\n'
    FileClose $InstallHandle
    IfErrors forge_state_failed
  ${EndIf}
  ClearErrors
  FileOpen $InstallHandle "$APPDATA\EcosystemRunner\runner-mode.json" w
  IfErrors runner_state_failed
  FileWrite $InstallHandle '{"mode": "$runner_mode"}$\r$\n'
  FileClose $InstallHandle
  IfErrors runner_state_failed
  Return
  forge_state_failed:
  Push "write runner-forge.json"
  Call Install_StateFailed
  runner_state_failed:
  Push "write runner-mode.json"
  Call Install_StateFailed
FunctionEnd

Function Install_StateFailed
  Pop $0
  Push "state-file"
  Push $0
  Push "49"
  Call LogStep
  MessageBox MB_OK|MB_ICONSTOP "The state file could not be written. See the step log for the file name." /SD IDOK
  SetErrorLevel 49
  Quit
FunctionEnd

Function Install_UninstallerFailed
  Push "uninstaller"
  Push "WriteUninstaller"
  Push "48"
  Call LogStep
  MessageBox MB_OK|MB_ICONSTOP "The uninstaller could not be written. The uninstall entry was not updated." /SD IDOK
  SetErrorLevel 48
  Quit
FunctionEnd

Function Install_Footprint
  Call Elevate_IsAdmin
  ${If} $elev_isadmin == 0
    SetErrorLevel 38
    Abort "Administrator rights are required: nothing was installed."
  ${EndIf}
  SetShellVarContext all
  SetRegView 64
  Call Winsys_FolderCheck
  StrCpy $R8 $1
  ${If} $R8 == "abse"
    Call Winsys_FolderCreate
  ${EndIf}
  Call Winsys_FolderLock
  ClearErrors
  FileOpen $InstallHandle "$APPDATA\EcosystemRunner\installer-state.json" w
  IfErrors state_failed
  FileWrite $InstallHandle '{"schema_version": 1, "installer_version": "${INSTALLER_VERSION}"}$\r$\n'
  FileClose $InstallHandle
  IfErrors state_failed
  Goto state_done
  state_failed:
  Push "write installer-state.json"
  Call Install_StateFailed
  state_done:
  Call Licence_WriteRecord
  Call Install_RunnerState
  ${If} $runner_mode == "github"
  ${OrIf} $runner_mode == "gitlab"
    Call Install_Payload
    Call Winsys_CreateService
  ${EndIf}
  ClearErrors
  WriteUninstaller "$APPDATA\EcosystemRunner\uninstall.exe"
  IfErrors 0 uninstaller_ready
  Call Install_UninstallerFailed
  uninstaller_ready:
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner" "DisplayName" "Ecosystem Runner"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner" "DisplayVersion" "${INSTALLER_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner" "UninstallString" '"$APPDATA\EcosystemRunner\uninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner" "QuietUninstallString" '"$APPDATA\EcosystemRunner\uninstall.exe" /S'
  Call Image_Pull
FunctionEnd
