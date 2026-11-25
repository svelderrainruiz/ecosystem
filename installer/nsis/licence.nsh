; Licence gate and local record (SL-16b, INST-REQ-018/073/074). Nothing here uses the network; the record stays on this PC.
; Exit 35 = licence-not-accepted, exit 36 = image-not-pinned (schema.json exit_codes).

; Silent runs: with an image chosen, an unpinned pair is refused first (36), then anything but "yes" in BOTH answers (35).
; One step is logged (the names only, never a value); nothing is written and nothing is pulled.
Var LicHandle

Function Licence_SilentGate
  ${If} $in_image_variant == ""
    Return
  ${EndIf}
  Call Image_Known
  ${If} $R9 != ""
    Push "image"
    Call Carried_Box
    Push "image-not-pinned"
    Push "image"
    Push "36"
    Call LogStep
    SetErrorLevel 36
    Quit
  ${EndIf}
  ${If} $in_ni_licence_held != "yes"
  ${OrIf} $in_engine_licence_accepted != "yes"
    Push "licences"
    Call Carried_Box
    Push "licence-not-accepted"
    Push "licences"
    Push "35"
    Call LogStep
    SetErrorLevel 35
    Quit
  ${EndIf}
FunctionEnd

; $R9 is 1 when an image is chosen and both answers are yes.
Function Licence_Ready
  StrCpy $R9 0
  ${If} $in_image_variant != ""
  ${AndIf} $in_ni_licence_held == "yes"
  ${AndIf} $in_engine_licence_accepted == "yes"
    StrCpy $R9 1
  ${EndIf}
FunctionEnd

; Same bytes as licences.write_record: {"ni_development_licence_held": "yes", "utc": "<UTC>Z"} and a line end.
Function Licence_WriteRecord
  Call Licence_Ready
  ${If} $R9 != "1"
    Return
  ${EndIf}
  Call LogUtcNow
  ClearErrors
  FileOpen $LicHandle "$APPDATA\EcosystemRunner\licence-record.json" w
  IfErrors record_failed
  FileWrite $LicHandle '{"ni_development_licence_held": "yes", "utc": "$LogY-$LogMo-$LogD'
  FileWrite $LicHandle 'T$LogH:$LogMi:$LogS'
  FileWrite $LicHandle 'Z"}$\n'
  FileClose $LicHandle
  IfErrors write_failed
  Return
  write_failed:
  Delete "$APPDATA\EcosystemRunner\licence-record.json"
  Push "licence-record"
  Push "FileWrite licence-record.json"
  Push "37"
  Call LogStep
  SetErrorLevel 37
  Abort "The licence record could not be written: installation stopped."
  record_failed:
  Push "licence-record"
  Push "FileOpen licence-record.json"
  Push "37"
  Call LogStep
  SetErrorLevel 37
  Abort "The licence record could not be written: installation stopped."
FunctionEnd
