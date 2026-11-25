; Installer entry. One include line per .nsh of a slice; each slice adds only its own line.
Unicode true
RequestExecutionLevel user
!ifdef OUTFILE
  OutFile "${OUTFILE}"
!else
  OutFile "installer.exe"
!endif

!include "trust.nsh"
!include "cmdline.nsh"
!include "log.nsh"
!include "dialog.nsh"
!include "screens.nsh"
!include "elevate.nsh"
!include "runner-github.nsh"
!include "runner-local.nsh"
!include "runner-gitlab.nsh"
!include "licence.nsh"
!include "image.nsh"
!include "install.nsh"
!include "winsys.nsh"
!include "update.nsh"
; Page order: choices, secrets, then the no-administrator page or the list screen, and only then the prompt.
Page custom Page_mode_Pre Page_mode_Leave
Page custom Page_folders Page_folders_Leave
Page custom Page_forge Page_forge_Leave
Page custom Page_network Page_network_Leave
Page custom Page_labview Page_labview_Leave
Page custom Page_image Page_image_Leave
Page custom Page_licences Page_licences_Leave
Page custom Page_secrets Page_secrets_Leave
Page custom Page_noadmin
Page custom Page_elevation Page_elevation_Leave
Page instfiles

Section
  Call Update_Route
SectionEnd

; A command line of 1023 characters or more first (exit 50, #136), then the secret options (exit 32 or 33 before anything else), then the silent keys and the mode, then the trust check and the elevation gate. The elevated copy of an interactive run (Carried_Detect,
; SL-21b) reads the answers its first window handed over through the same key path as a silent run, and every page they are for is skipped.
Function .onInit
  !insertmacro RefuseLongCommandLine
  !insertmacro RefuseSecretOptions
  Call Log_InitPaths
  StrCpy $LogExistingOnly 1
  Call Carried_Detect
  ${If} ${Silent}
  ${OrIf} $carried == 1
    !insertmacro ParseSilentKeys
    Call Mode_FromSilent
    !insertmacro ValidateSilentKeys
    Call Licence_SilentGate
  ${EndIf}
  StrCpy $LogExistingOnly 0
  Call TrustCheck
  Call Elevate_SilentGate
  Call Update_Detect
  Call Runner_GitlabInstallGate
FunctionEnd
!include "uninstall.nsh"
