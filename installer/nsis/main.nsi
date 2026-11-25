; Installer entry. One include line per .nsh of a slice; each slice adds only its own line.
Unicode true
RequestExecutionLevel user
!ifdef OUTFILE
  OutFile "${OUTFILE}"
!else
  OutFile "installer.exe"
!endif
; An experimental installer (issue 329): the window caption (also the title of every box) and the branding line say so.
; The branding line is one line of 108 dialog units between Cancel and < Back; a longer text is cut off.
Caption "Ecosystem Runner Setup (EXPERIMENTAL)"
UninstallCaption "Ecosystem Runner Uninstall (EXPERIMENTAL)"
BrandingText "EXPERIMENTAL (test build)"

!include "cmdline.nsh"
!include "log.nsh"
!include "dialog.nsh"
!include "screens.nsh"
; after screens.nsh ($carried, Dialog_Create) for the signer page, before elevate.nsh (it carries $TrustSigner)
!include "trust.nsh"
!include "elevate.nsh"
!include "runner-github.nsh"
!include "runner-local.nsh"
!include "runner-gitlab.nsh"
!include "licence.nsh"
!include "image.nsh"
!include "install.nsh"
!include "winsys.nsh"
!include "update.nsh"
; Page order: the signer fingerprint (only for a window started without /SIGNER=, INST-REQ-103), choices, secrets, then the no-administrator page or the
; list screen, and only then the prompt.
Page custom Page_signer Page_signer_Leave
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
; The experimental warning (issue 329) is the first box of an interactive run, in front of every trust box (a malformed signer included); OK only closes it and changes no exit code.
; A window started without /SIGNER= (a double click) is not refused here: TrustCheck leaves the fingerprint to the signer page (INST-REQ-103), and the checks after it do not read it.
; A silent run and the elevated copy ($carried 1, its first window already showed it) never show it.
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
  ${IfNot} ${Silent}
  ${AndIf} $carried != 1
    MessageBox MB_OK|MB_ICONEXCLAMATION "This is an EXPERIMENTAL installer (test build). It is not for production use: run it only where you can undo the changes." /SD IDOK
  ${EndIf}
  Call TrustCheck
  Call Elevate_SilentGate
  Call Update_Detect
  Call Runner_GitlabInstallGate
FunctionEnd
!include "uninstall.nsh"
