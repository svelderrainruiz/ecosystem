; GUEST6B probe P1: does RMDir /r follow a junction out of the folder it removes? Writes one line to probe-p1.txt next to the exe:
; "survives" (the file outside the folder is still there) or "gone" (NSIS followed the junction), plus the return code of the setup.
; Not part of the installer; built by pack.py.
Unicode true
RequestExecutionLevel user
SilentInstall silent

Section
  nsExec::ExecToStack 'cmd /c mkdir "$TEMP\v\t" & echo x>"$TEMP\v\t\f" & mkdir "$TEMP\v\r" & mklink /J "$TEMP\v\r\j" "$TEMP\v\t"'
  Pop $0
  Pop $1
  StrCpy $4 "absent"
  IfFileExists "$TEMP\v\t\f" 0 +2
  StrCpy $4 "present"
  RMDir /r "$TEMP\v\r"
  StrCpy $2 "survives"
  IfFileExists "$TEMP\v\t\f" report 0
  StrCpy $2 "gone"
  report:
  FileOpen $3 "$EXEDIR\probe-p1.txt" w
  FileWrite $3 "$2 (file outside the folder before the removal: $4; setup return code $0)"
  FileClose $3
SectionEnd
