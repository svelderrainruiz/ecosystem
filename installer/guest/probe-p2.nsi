; GUEST6B probe P2: a declined elevation. Run it as a STANDARD user (UAC cannot be answered): ExecShell runas on this very exe with /X.
; Writes one line to probe-p2.txt (is the error flag set?), then leaves with Quit; the exit code is read from outside: 38 when the
; flag was set (what the installer would return), 99 when it was clear.
; The /X copy (if an elevation were ever granted) quits at once. Not part of the installer; built by pack.py.
Unicode true
RequestExecutionLevel user
SilentInstall silent
!include "FileFunc.nsh"
!insertmacro GetParameters

Section
  ${GetParameters} $0
  StrCmp $0 "/X" 0 first
  Quit
  first:
  ClearErrors
  ExecShell "runas" "$EXEPATH" "/X"
  IfErrors flag_set flag_clear
  flag_set:
  StrCpy $1 "error flag set"
  SetErrorLevel 38
  Goto report
  flag_clear:
  StrCpy $1 "error flag clear"
  SetErrorLevel 99
  report:
  FileOpen $2 "$EXEDIR\probe-p2.txt" w
  FileWrite $2 "$1"
  FileClose $2
  Quit
SectionEnd
