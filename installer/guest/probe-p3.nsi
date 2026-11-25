; GUEST6B probe P3: does ${WordFind} set the error flag only with the E option? One line to probe-p3.txt: where the E+n loop ended
; (5 expected for four words), and whether the same call without E ever set the flag in 50 tries (never expected).
; Both loops are capped at 50 so that the probe itself cannot hang. Not part of the installer; built by pack.py.
Unicode true
RequestExecutionLevel user
SilentInstall silent
!include "WordFunc.nsh"
!insertmacro WordFind

Section
  StrCpy $R8 0
  loop_e:
  IntOp $R8 $R8 + 1
  ClearErrors
  ${WordFind} '"C:\a b.exe" /S /MODE=local' " " "E+$R8" $R1
  IfErrors done_e 0
  IntCmp $R8 50 done_e loop_e done_e
  done_e:
  StrCpy $R7 $R8
  StrCpy $R8 0
  StrCpy $R6 "never"
  loop_n:
  IntOp $R8 $R8 + 1
  ClearErrors
  ${WordFind} '"C:\a b.exe" /S /MODE=local' " " "+$R8" $R1
  IfErrors flagged 0
  IntCmp $R8 50 report loop_n report
  flagged:
  StrCpy $R6 "set at $R8"
  report:
  FileOpen $0 "$EXEDIR\probe-p3.txt" w
  FileWrite $0 "with E the loop ended at R8=$R7; without E the flag was $R6 (cap 50)"
  FileClose $0
SectionEnd
