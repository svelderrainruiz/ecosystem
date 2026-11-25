; Trust chain (ARCH-1): first-run confirmation, stored signer, signer change. Mirrors installer/trust.py.
; The signer fingerprint arrives as /SIGNER=<64 hex>. The launcher that checked the signature before this installer
; started is the trust boundary: this code only refuses a malformed value, it cannot verify who signed.
; A window started without it (a double click: not silent, not the elevated copy, /SIGNER= missing or empty) asks for it on the signer page,
; the first page (INST-REQ-103), and runs the same checks when Next is selected; a /SIGNER= with a malformed value is still refused in .onInit.
; The stored file holds 64 hex digits and one newline (INST-REQ-002). An existing stored file is never a first run:
; anything but that exact content stops the installer.
; Silent runs never confirm: a first run or a changed signer stops with exit code 3 (INST-REQ-003).
; Confirmation boxes default to No, so Enter never accepts a fingerprint.

!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "nsDialogs.nsh"

Var TrustSigner
Var TrustStored
Var TrustStoreFile
; 1 while the signer page asks for the fingerprint: then a stop ends the installer with Quit, because Abort in a Leave function only keeps the page.
Var TrustAsk
Var TrustText
Var TrustTyped

; Return 64 canonical lowercase hex digits, or the empty string for malformed input.
Function TrustCanonicalHex64
  Exch $R0
  Push $R1
  Push $R2
  Push $R3
  Push $R4
  Push $R5
  StrCpy $R5 ""
  StrLen $R1 $R0
  IntCmp $R1 64 0 TrustHexBad TrustHexBad
  StrCpy $R1 0
  TrustHexLoop:
    IntCmp $R1 64 TrustHexOk 0 0
    StrCpy $R2 $R0 1 $R1
    StrCpy $R3 0
    TrustHexAlpha:
      StrCpy $R4 "0123456789abcdefABCDEF" 1 $R3
      StrCmpS $R2 $R4 TrustHexNext
      IntOp $R3 $R3 + 1
      IntCmp $R3 22 TrustHexBad TrustHexAlpha TrustHexBad
    TrustHexNext:
    StrCpy $R4 "0123456789abcdefabcdef" 1 $R3
    StrCpy $R5 "$R5$R4"
    IntOp $R1 $R1 + 1
    Goto TrustHexLoop
  TrustHexOk:
  StrCpy $R0 $R5
  Goto TrustHexEnd
  TrustHexBad:
  StrCpy $R0 ""
  TrustHexEnd:
  Pop $R5
  Pop $R4
  Pop $R3
  Pop $R2
  Pop $R1
  Exch $R0
FunctionEnd

; Push the reason, Call TrustRefuse: stops with exit code 3, never continues.
Function TrustRefuse
  Pop $0
  IfSilent +2
  MessageBox MB_OK|MB_ICONSTOP "$0 Nothing was started."
  SetErrorLevel 3
  Call TrustStop
FunctionEnd

; Ends the installer: Abort in .onInit (as before the signer page); from the signer page with exit code 3 and Quit.
Function TrustStop
  StrCmp $TrustAsk 1 0 TrustStopInit
  SetErrorLevel 3
  Quit
  TrustStopInit:
  Abort
FunctionEnd

Function TrustCheck
  StrCpy $TrustAsk 0
  Push "/SIGNER="
  Call Cmdline_Get
  Pop $TrustSigner
  ; a window started without a fingerprint: the signer page asks for it and calls TrustVerify
  ${IfNot} ${Silent}
  ${AndIf} $carried != 1
  ${AndIf} $TrustSigner == ""
    StrCpy $TrustAsk 1
    Return
  ${EndIf}
  Push $TrustSigner
  Call TrustCanonicalHex64
  Pop $TrustSigner
  StrCmp $TrustSigner "" 0 +3
    Push "The signer fingerprint is missing or malformed. Start the installer with /SIGNER= and the 64 hex digits of the published fingerprint."
    Call TrustRefuse
  Call TrustVerify
FunctionEnd

; $TrustSigner holds 64 canonical hex digits: compare it with the stored signer, ask on a first run or a changed signer, store it.
Function TrustVerify
  StrCpy $TrustStoreFile "$LOCALAPPDATA\EcosystemInstaller\signer.sha256"
  IfFileExists "$TrustStoreFile" TrustReadFile TrustFirstRun
  TrustReadFile:
  ClearErrors
  FileOpen $0 "$TrustStoreFile" r
  IfErrors TrustStoreBad
  FileRead $0 $TrustStored
  ; a second line is garbage
  FileRead $0 $2
  IfErrors +2
  StrCpy $TrustStored "x"
  FileClose $0
  ; after the 64 digits only a line end may follow
  StrCpy $3 $TrustStored 64 64
  StrCmp $3 "" TrustTrimmed
  StrCmp $3 "$\n" TrustTrimmed
  StrCmp $3 "$\r$\n" TrustTrimmed
  Goto TrustStoreBad
  TrustTrimmed:
  StrCpy $TrustStored $TrustStored 64
  Push $TrustStored
  Call TrustCanonicalHex64
  Pop $TrustStored
  StrCmp $TrustStored "" 0 TrustCompare
  TrustStoreBad:
  Push "The stored signer file is damaged, so the stored signer cannot be read."
  Call TrustRefuse
  TrustCompare:
  StrCmpS $TrustStored $TrustSigner TrustDone
  ; different signer: show old and new, ask again; silent runs stop before any build step
  IfSilent TrustStopSilent
  MessageBox MB_YESNO|MB_ICONEXCLAMATION|MB_DEFBUTTON2 "The signer changed.$\r$\n$\r$\nStored:$\r$\n$TrustStored$\r$\n$\r$\nNew:$\r$\n$TrustSigner$\r$\n$\r$\nContinue only if the new fingerprint matches both published places." IDYES TrustStore
  Call TrustStop
  TrustFirstRun:
  IfSilent TrustStopSilent
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "First run. The signer fingerprint is:$\r$\n$\r$\n$TrustSigner$\r$\n$\r$\nDoes it match the fingerprints published in the two independent places?" IDYES TrustStore
  Call TrustStop
  TrustStore:
  ClearErrors
  CreateDirectory "$LOCALAPPDATA\EcosystemInstaller"
  FileOpen $0 "$TrustStoreFile" w
  IfErrors TrustWriteBad
  FileWrite $0 "$TrustSigner$\n"
  FileClose $0
  IfErrors TrustWriteBad
  Goto TrustDone
  TrustWriteBad:
  Push "The signer fingerprint could not be stored."
  Call TrustRefuse
  TrustStopSilent:
  SetErrorLevel 3
  Abort
  TrustDone:
FunctionEnd

; INST-REQ-103: the signer page, the first page. Shown only when TrustCheck left the fingerprint to it ($TrustAsk 1); the elevated copy and a run
; started with /SIGNER= never show it. Back from the next page shows it again with the fingerprint already checked: Next with the same one asks nothing.
Function Page_signer
  ${If} $carried == 1
    Abort
  ${EndIf}
  ${If} $TrustAsk != 1
    Abort
  ${EndIf}
  !insertmacro Dialog_Create
  ${NSD_CreateLabel} 0u 0u 100% 20u "Type the signer fingerprint: the 64 hex digits published in the two independent places. Then select Next."
  Pop $0
  ${NSD_CreateLabel} 0u 24u 100% 8u "Signer fingerprint (64 hex digits)"
  Pop $0
  ${NSD_CreateText} 0u 33u 100% 12u "$TrustSigner"
  Pop $TrustText
  SendMessage $TrustText ${EM_LIMITTEXT} 1023 0
  nsDialogs::Show
FunctionEnd

; A malformed fingerprint keeps the page with a box that names the problem. A valid one runs the checks of a /SIGNER= start (TrustVerify); a No or a
; refusal there ends the installer with exit code 3 (TrustStop) and nothing is stored.
Function Page_signer_Leave
  ${NSD_GetText} $TrustText $TrustTyped
  Push $TrustTyped
  Call TrustCanonicalHex64
  Pop $TrustSigner
  ${If} $TrustSigner == ""
    StrLen $0 $TrustTyped
    ${If} $0 == 0
      MessageBox MB_OK|MB_ICONEXCLAMATION "No signer fingerprint was typed. Type the 64 hex digits of the published fingerprint, then select Next." /SD IDOK
    ${ElseIf} $0 != 64
      MessageBox MB_OK|MB_ICONEXCLAMATION "The signer fingerprint has $0 characters, not 64. Type the 64 hex digits (0 to 9, a to f) again, then select Next." /SD IDOK
    ${Else}
      MessageBox MB_OK|MB_ICONEXCLAMATION "The signer fingerprint holds a character that is not a hex digit (0 to 9, a to f). Type it again, then select Next." /SD IDOK
    ${EndIf}
    Abort
  ${EndIf}
  ; Update_Detect (.onInit) switches an administrator window to the all-users folders; the stored signer belongs to the user.
  SetShellVarContext current
  Call TrustVerify
  ; the folders as .onInit left them for the pages that follow
  Call Update_Detect
FunctionEnd
