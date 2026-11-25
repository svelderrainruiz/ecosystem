; Elevation moment (ARCH-5) and footprint (ARCH-6). INST-REQ-027..032, 078, 079, 089.
; Everything before Page_elevation runs unelevated (RequestExecutionLevel user in main.nsi). The administrator prompt
; is raised in ONE place, Elevate_Raise, called only from Page_elevation_Leave. UNVERIFIED (architecture.md section 3):
; whether the relaunch-with-runas approach drives user level and administrator level as the flow needs. If the guest
; run says no, only Elevate_Raise (and the level line in main.nsi) change; the screen, the gate and the footprint stay.
; Names, paths and the exit code come from installer/footprint.json; installer/footprint.py scans this file.
; The answers cross the prompt (SL-21b, #117): the elevated copy is a NEW process, so Elevate_Raise hands it every non-secret answer as a /KEY=value token (Carry_Answers in
; screens.nsh, Carry_One below) and the copy reads them like a silent run (Carried_Detect, then the key path of .onInit) without showing those pages again. Secrets never go on a command line.
!pragma warning disable 6010
!include "LogicLib.nsh"
!include "nsDialogs.nsh"
!include "FileFunc.nsh"

Var elev_isadmin
Var carry_args
Var carry_room
Var carry_bad
Var carry_l
Var carry_k
Var carry_v
Var carry_q
Var carry_t
Var carry_n

Function Elevate_IsAdmin
  UserInfo::GetAccountType
  Pop $0
  ${If} $0 == "Admin"
    StrCpy $elev_isadmin 1
  ${Else}
    StrCpy $elev_isadmin 0
  ${EndIf}
FunctionEnd

; INST-REQ-078: silent mode never prompts; when not already elevated it ends with its own exit code.
Function Elevate_SilentGate
  Call Elevate_IsAdmin
  ${If} ${Silent}
  ${AndIf} $elev_isadmin == 0
    SetErrorLevel 38
    Quit
  ${EndIf}
FunctionEnd

; INST-REQ-028: lists exactly what will change, before the prompt.
Function Page_elevation
  Call Elevate_IsAdmin
  ${If} $elev_isadmin == 1
    Abort
  ${EndIf}
  !insertmacro Dialog_Create
  ${NSD_CreateLabel} 0u 0u 100% 16u "The next step needs administrator rights. It changes exactly these things and nothing else:"
  Pop $0
  ${NSD_CreateLabel} 0u 20u 100% 10u "Service: EcosystemRunner, running under the virtual service account NT SERVICE\EcosystemRunner"
  Pop $0
  ${NSD_CreateLabel} 0u 32u 100% 10u "Folder: $MachineFolder (the machine's program-data location)"
  Pop $0
  ${NSD_CreateLabel} 0u 44u 100% 10u "Uninstall entry: one entry named EcosystemRunner"
  Pop $0
  ${NSD_CreateLabel} 0u 56u 100% 20u "Rights: create and start the service, write the folder, write the uninstall entry. Choose Next to see the Windows administrator prompt."
  Pop $0
  nsDialogs::Show
FunctionEnd

; INST-REQ-029: the only caller of Elevate_Raise. It comes back only when nothing was handed over (the prompt was declined, or an answer could not be carried): Abort in a Leave function
; keeps the page, so the answers stay and Next tries again.
Function Page_elevation_Leave
  Call Elevate_IsAdmin
  ${If} $elev_isadmin == 0
    Call Elevate_Raise
    Abort
  ${EndIf}
FunctionEnd

; The single place that raises rights. Replace this function only if the elevation approach is redesigned.
; The relaunch gets ONE parameter string, built here and nowhere else (the program path is not copied from $CMDLINE: it would reach the child a second time). In this order:
;   /NCRC and /SIGNER=, the only two of the parent's own words the child needs (/D= is cut out of the command line by NSIS before any script sees it, and the child checks the signer itself;
;   a parent started without /SIGNER= hands over the fingerprint typed on its signer page, INST-REQ-103); an unknown or
;   bad word typed on the parent's command line is dropped, so it cannot end the child with exit 30 or 31 after the prompt; /NCRC is first because the NSIS stub reads it blank by blank and an
;   answer that ends in a blank leaves a lone quote that hides every later word from it; then /ELEVATED, then the answers (Carry_Answers), the non-secret ones that are not blank.
; Nothing is handed over when an answer cannot be carried: the page stays and a message names it (issue 117). Only a successful hand-over quits. ExecShell sets the error flag when the user
; declines the prompt and never clears it on success, so the flag is cleared first. A decline keeps the installer open with a message (issue 111, problem 1).
Function Elevate_Raise
  Call Carry_Begin
  Push "/NCRC"
  Call Cmdline_Has
  Pop $0
  ${If} $0 == 1
    Push "The no-integrity-check option"
    Push "/NCRC"
    Call Carry_Token
  ${EndIf}
  Push "/SIGNER="
  Call Cmdline_Get
  Pop $0
  ; a window started without /SIGNER= hands over the fingerprint its signer page checked (64 lowercase hex digits)
  ${If} $0 == ""
    StrCpy $0 $TrustSigner
  ${EndIf}
  ${If} $0 != ""
    Push "The signer fingerprint"
    Push "/SIGNER="
    Push $0
    Call Carry_One
  ${EndIf}
  Push "The elevation flag"
  Push "/ELEVATED"
  Call Carry_Token
  Call Carry_Answers
  ${If} $carry_bad != ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "These answers cannot be handed to the administrator step, so it was NOT started: $carry_bad. Choose Back, change or shorten them, then choose Next." /SD IDOK
    Return
  ${EndIf}
  ClearErrors
  ExecShell "runas" "$EXEPATH" "$carry_args"
  IfErrors declined
  Quit
  declined:
  MessageBox MB_OK|MB_ICONEXCLAMATION "The installation needs administrator rights and has NOT started. Choose Next to see the Windows administrator prompt again, or Cancel to leave." /SD IDOK
FunctionEnd

; The elevated copy refuses a whole command line of 1023 characters because it cannot tell it from a cut one (#136). Start with 1022 and reserve the quoted program path (#186).
; Each token costs its length and one blank in $carry_room (the first pays for the blank after the program path).
Function Carry_Begin
  StrCpy $carry_args ""
  StrCpy $carry_bad ""
  StrLen $carry_n "$EXEPATH"
  IntOp $carry_room 1022 - $carry_n
  IntOp $carry_room $carry_room - 2
FunctionEnd

; Keeps a label in $carry_bad, the answers that were not handed over.
Function Carry_Bad
  ${If} $carry_bad == ""
    StrCpy $carry_bad $carry_l
  ${Else}
    StrCpy $carry_bad "$carry_bad, $carry_l"
  ${EndIf}
FunctionEnd

; Push the label, then the whole token, Call Carry_Token. The token goes on after a blank when it fits in $carry_room, else its label is kept in $carry_bad. A string cut at 1023 characters
; measures 1023 and the room is never more than 1019 (even a one-character program path has two quotes), so a token that was cut while it was built is refused too.
Function Carry_Token
  Pop $carry_t
  Pop $carry_l
  StrLen $carry_n $carry_t
  IntOp $carry_n $carry_n + 1
  ${If} $carry_n > $carry_room
    Call Carry_Bad
    Return
  ${EndIf}
  IntOp $carry_room $carry_room - $carry_n
  ${If} $carry_args == ""
    StrCpy $carry_args $carry_t
  ${Else}
    StrCpy $carry_args "$carry_args $carry_t"
  ${EndIf}
FunctionEnd

; Push the label, the key with its "=" and the value, Call Carry_One. The answer goes on as /KEY=value, the value in the quoting of Cmdline_Quote. Its label is kept in $carry_bad instead when
; the elevated copy could not read it back: a double quote (the command line has no escape for one, and the url and list screens let one through), or a blank followed by "/" or "-": the stub of an
; NSIS installer reads every blank-separated word for /S, /NCRC and /D= (the last cuts the line), and the secret refusal reads every blank-separated word, quotes or not, so a word "-" is exit 33 and
; a word that starts with "/" and names a token is exit 32, both after the prompt and with no message; or a value that ends in a blank: the stub then reads its closing quote as the start of an argument
; and pairs every later quote the wrong way round, so the first word of a later quoted value, "/S" for one, would be read as a switch. Everything else crosses as typed.
Function Carry_One
  Pop $carry_v
  Pop $carry_k
  Pop $carry_l
  StrCpy $carry_q '"'
  ${StrStr} $carry_t $carry_v $carry_q
  ${If} $carry_t == ""
    ${StrStr} $carry_t $carry_v " /"
  ${EndIf}
  ${If} $carry_t == ""
    ${StrStr} $carry_t $carry_v " -"
  ${EndIf}
  StrCpy $carry_n $carry_v 1 -1
  ${If} $carry_t != ""
  ${OrIf} $carry_n == " "
    Call Carry_Bad
    Return
  ${EndIf}
  Push $carry_v
  Call Cmdline_Quote
  Pop $carry_t
  StrCpy $carry_t "$carry_k$carry_t"
  Push $carry_l
  Push $carry_t
  Call Carry_Token
FunctionEnd

; The elevated copy of this installer: /ELEVATED, a window (not a silent run) and the /MODE= the first window handed over (it cannot leave its page without a mode). $carried is 1 then: .onInit
; reads the answers like a silent run and every page they are for is skipped. /ELEVATED alone, or without a mode, is an ordinary interactive run: every page shows, as before.
Function Carried_Detect
  StrCpy $carried 0
  ${If} ${Silent}
    Return
  ${EndIf}
  Push "/ELEVATED"
  Call Cmdline_Has
  Pop $0
  ${If} $0 != 1
    Return
  ${EndIf}
  Push "/MODE="
  Call Cmdline_Get
  Pop $0
  ${If} ${Errors}
    Return
  ${EndIf}
  StrCpy $carried 1
FunctionEnd

; The elevated copy cannot ask anything: an answer it does not accept is a bug or tampering, because the first window checked the same text. It shows ONE box naming the key (never the value)
; and its caller then ends with its own exit code, as a silent run does. Push the key, Call Carried_Box. A silent run shows nothing.
Function Carried_Box
  Pop $0
  ${If} $carried == 1
    MessageBox MB_OK|MB_ICONSTOP "The administrator step did not accept the answer $0 that the first window handed over. Nothing was started." /SD IDOK
  ${EndIf}
FunctionEnd

; INST-REQ-032, 079: without administrator rights only the per-user mode is offered, with the plain statement.
Function Page_noadmin
  Call Elevate_IsAdmin
  ${If} $elev_isadmin == 1
    Abort
  ${EndIf}
  !insertmacro Dialog_Create
  ${NSD_CreateLabel} 0u 0u 100% 20u "The runner needs administrator rights, and this PC session does not have them. Only the per-user mode is offered."
  Pop $0
  ${NSD_CreateRadioButton} 0u 24u 100% 12u "Local only (no forge)"
  Pop $0
  ${NSD_Check} $0
  nsDialogs::Show
FunctionEnd
