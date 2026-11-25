; Step log (ARCH-10). Mirrors installer/log.py: one line per step, command, exit code and UTC ISO 8601 time (INST-REQ-046/047).
; Usage: Push "<step>"; Push "<command>"; Push "<exit code>"; Call LogStep
; Step and command are JSON-escaped and may contain user text. Never pass secrets: give command names without values.
; Each line also names the Windows zone (TimeZoneKeyName, a name only, INST-REQ-052); the display side maps it with zones.json.
; The log file is steps.jsonl in the machine folder (ProgramData\EcosystemRunner, inside the footprint).
; UTC = local time + ActiveTimeBias minutes (the bias already includes daylight saving); the date arithmetic is integer-only
; (days from civil date) and equals log.utc_from_local() in installer/log.py, which tests prove against datetime.

!include "FileFunc.nsh"
!include "LogicLib.nsh"
!insertmacro GetTime

Var LogStepName
Var LogCommand
Var LogExit
Var LogHandle
Var LogY
Var LogMo
Var LogD
Var LogH
Var LogMi
Var LogS
Var LogBias
Var LogZone
Var LogT1
Var LogT2
Var LogT3
Var LogT4

; Strip one leading zero so IntOp never reads "08" as octal.
!macro LogUnpad var
  StrCpy $LogT1 ${var} 1
  StrCmp $LogT1 "0" 0 +2
  StrCpy ${var} ${var} "" 1
!macroend

Function LogUtcNow
  ${GetTime} "" "L" $LogD $LogMo $LogY $LogT1 $LogH $LogMi $LogS
  !insertmacro LogUnpad $LogD
  !insertmacro LogUnpad $LogMo
  !insertmacro LogUnpad $LogH
  !insertmacro LogUnpad $LogMi
  !insertmacro LogUnpad $LogS
  ReadRegDWORD $LogBias HKLM "SYSTEM\CurrentControlSet\Control\TimeZoneInformation" "ActiveTimeBias"
  ; local date to days since 1970-01-01 (LogT3), year Y-1 and month +9 for January and February
  IntCmp $LogMo 2 jan_feb jan_feb mar_dec
  jan_feb:
    IntOp $LogT1 $LogY - 1
    IntOp $LogT3 $LogMo + 9
    Goto date_base
  mar_dec:
    StrCpy $LogT1 $LogY
    IntOp $LogT3 $LogMo - 3
  date_base:
  IntOp $LogT2 $LogT1 / 400
  IntOp $LogT4 $LogT2 * 400
  IntOp $LogT1 $LogT1 - $LogT4
  IntOp $LogT3 $LogT3 * 153
  IntOp $LogT3 $LogT3 + 2
  IntOp $LogT3 $LogT3 / 5
  IntOp $LogT3 $LogT3 + $LogD
  IntOp $LogT3 $LogT3 - 1
  IntOp $LogT4 $LogT1 * 365
  IntOp $LogT3 $LogT3 + $LogT4
  IntOp $LogT4 $LogT1 / 4
  IntOp $LogT3 $LogT3 + $LogT4
  IntOp $LogT4 $LogT1 / 100
  IntOp $LogT3 $LogT3 - $LogT4
  IntOp $LogT2 $LogT2 * 146097
  IntOp $LogT3 $LogT3 + $LogT2
  IntOp $LogT3 $LogT3 - 719468
  ; local minutes, then UTC minutes
  IntOp $LogT3 $LogT3 * 1440
  IntOp $LogT4 $LogH * 60
  IntOp $LogT3 $LogT3 + $LogT4
  IntOp $LogT3 $LogT3 + $LogMi
  IntOp $LogT3 $LogT3 + $LogBias
  IntOp $LogT1 $LogT3 / 1440
  IntOp $LogT4 $LogT1 * 1440
  IntOp $LogT3 $LogT3 - $LogT4
  IntOp $LogH $LogT3 / 60
  IntOp $LogMi $LogT3 % 60
  ; UTC days (LogT1) to civil date
  IntOp $LogT1 $LogT1 + 719468
  IntOp $LogT2 $LogT1 / 146097
  IntOp $LogT4 $LogT2 * 146097
  IntOp $LogT1 $LogT1 - $LogT4
  ; LogT2 = era, LogT1 = day of era
  IntOp $LogT3 $LogT1 / 1460
  IntOp $LogT3 $LogT1 - $LogT3
  IntOp $LogT4 $LogT1 / 36524
  IntOp $LogT3 $LogT3 + $LogT4
  IntOp $LogT4 $LogT1 / 146096
  IntOp $LogT3 $LogT3 - $LogT4
  IntOp $LogT3 $LogT3 / 365
  ; LogT3 = year of era
  IntOp $LogY $LogT2 * 400
  IntOp $LogY $LogY + $LogT3
  IntOp $LogT4 $LogT3 * 365
  IntOp $LogT2 $LogT3 / 4
  IntOp $LogT4 $LogT4 + $LogT2
  IntOp $LogT2 $LogT3 / 100
  IntOp $LogT4 $LogT4 - $LogT2
  IntOp $LogT1 $LogT1 - $LogT4
  ; LogT1 = day of year counted from March, LogT2 = month index
  IntOp $LogT2 $LogT1 * 5
  IntOp $LogT2 $LogT2 + 2
  IntOp $LogT2 $LogT2 / 153
  IntOp $LogD $LogT2 * 153
  IntOp $LogD $LogD + 2
  IntOp $LogD $LogD / 5
  IntOp $LogD $LogT1 - $LogD
  IntOp $LogD $LogD + 1
  IntCmp $LogT2 10 idx_high idx_low idx_high
  idx_low:
    IntOp $LogMo $LogT2 + 3
    Goto month_done
  idx_high:
    IntOp $LogMo $LogT2 - 9
  month_done:
  IntCmp $LogMo 2 add_year add_year fmt
  add_year:
    IntOp $LogY $LogY + 1
  fmt:
  IntFmt $LogMo "%02d" $LogMo
  IntFmt $LogD "%02d" $LogD
  IntFmt $LogH "%02d" $LogH
  IntFmt $LogMi "%02d" $LogMi
  IntFmt $LogS "%02d" $LogS
FunctionEnd

Var MachineFolder
Var LogPath
Var LogExistingOnly

Function Log_InitPaths
  SetShellVarContext all
  StrCpy $MachineFolder "$APPDATA\EcosystemRunner"
  StrCpy $LogPath "$MachineFolder\steps.jsonl"
  SetShellVarContext current
FunctionEnd

; Stack: one chunk in, its JSON string contents out. NSIS strings cannot contain NUL.
; StrCmpS compares exactly; StrCmp is case-insensitive (lstrcmpi) and could match a character with no sort weight to a control.
Function LogJsonEscape
  Exch $0
  Push $1
  Push $2
  Push $3
  Push $4
  Push $5
  Push $R0
  StrCpy $1 ""
  StrLen $2 $0
  StrCpy $3 0
  next_char:
    IntCmp $3 $2 escaped
    StrCpy $4 $0 1 $3
    IntOp $3 $3 + 1
    StrCmpS $4 '\' 0 +3
      StrCpy $4 '\\'
      Goto append
    StrCmpS $4 '"' 0 +3
      StrCpy $4 '\"'
      Goto append
    StrCmpS $4 "$\t" 0 +3
      StrCpy $4 '\t'
      Goto append
    StrCmpS $4 "$\r" 0 +3
      StrCpy $4 '\r'
      Goto append
    StrCmpS $4 "$\n" 0 +3
      StrCpy $4 '\n'
      Goto append
    StrCpy $5 1
    control:
      IntFmt $R0 "%c" $5
      StrCmpS $4 $R0 0 +3
        IntFmt $4 "\u%04X" $5
        Goto append
      IntOp $5 $5 + 1
      IntCmp $5 32 append control
    append:
      StrCpy $1 "$1$4"
      Goto next_char
  escaped:
  StrCpy $0 $1
  Pop $R0
  Pop $5
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Exch $0
FunctionEnd

; Six bytes per escaped control: 128 input units always fit in the 1023-unit buffer.
!macro LogWriteField var
  ${Do}
    StrCpy $LogT1 ${var} 128
    Push $LogT1
    Call LogJsonEscape
    Pop $LogT1
    FileWrite $LogHandle $LogT1
    StrCpy ${var} ${var} "" 128
    StrLen $LogT1 ${var}
    ${If} $LogT1 == 0
      ${ExitDo}
    ${EndIf}
  ${Loop}
!macroend

Function LogStep
  Pop $LogExit
  Pop $LogCommand
  Pop $LogStepName
  StrCmp $LogExistingOnly 1 0 log_ready
  IfFileExists "$LogPath" log_ready done
  log_ready:
  Call LogUtcNow
  ReadRegStr $LogZone HKLM "SYSTEM\CurrentControlSet\Control\TimeZoneInformation" "TimeZoneKeyName"
  ClearErrors
  FileOpen $LogHandle "$LogPath" a
  IfErrors done
  FileSeek $LogHandle 0 END
  StrCmpS $LogExit "error" exec_error
  StrCmpS $LogExit "timeout" exec_error write_line
  exec_error:
  StrCpy $LogExit 'null, "exec_error": "$LogExit"'
  write_line:
  FileWrite $LogHandle '{"step": "'
  !insertmacro LogWriteField $LogStepName
  FileWrite $LogHandle '", "command": "'
  !insertmacro LogWriteField $LogCommand
  FileWrite $LogHandle '", "exit_code": $LogExit, "started": "$LogY-$LogMo-$LogD'
  FileWrite $LogHandle 'T$LogH:$LogMi:$LogS+00:00", "zone": "$LogZone"}$\r$\n'
  FileClose $LogHandle
  done:
FunctionEnd
