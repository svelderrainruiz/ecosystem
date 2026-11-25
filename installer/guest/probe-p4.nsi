; GUEST6B probe P4: the process exit code after SetErrorLevel 35 and, by the one parameter, /a Quit in .onInit, /b Quit in a section,
; /c Abort in a section, /d Quit in a function called from a section. The exit code is read from outside. Not part of the
; installer; built by pack.py.
Unicode true
RequestExecutionLevel user
SilentInstall silent
!include "FileFunc.nsh"
!insertmacro GetParameters
Var c

Function QuitHere
  Quit
FunctionEnd

Function .onInit
  ${GetParameters} $c
  SetErrorLevel 35
  StrCmp $c "/a" 0 +2
  Quit
FunctionEnd

Section
  StrCmp $c "/b" 0 +2
  Quit
  StrCmp $c "/c" 0 +2
  Abort
  StrCmp $c "/d" 0 +2
  Call QuitHere
SectionEnd
