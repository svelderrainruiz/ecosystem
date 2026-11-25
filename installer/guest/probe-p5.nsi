; GUEST6B probe P5: FileRead of one 1030-character line into a normal string register. Reads p5-in.txt next to the exe and writes the
; number of characters that arrived to probe-p5.txt (1023 expected). Not part of the installer; built by pack.py.
Unicode true
RequestExecutionLevel user
SilentInstall silent

Section
  FileOpen $1 "$EXEDIR\p5-in.txt" r
  FileRead $1 $0
  FileClose $1
  StrLen $2 $0
  FileOpen $3 "$EXEDIR\probe-p5.txt" w
  FileWrite $3 "characters read: $2 of 1030"
  FileClose $3
SectionEnd
