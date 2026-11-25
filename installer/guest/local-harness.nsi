; Guest harness: runs the real local-mode switch (SL-5) in a Windows guest and records the mode. Not part of the installer; built by pack.py.
Unicode true
RequestExecutionLevel admin
SilentInstall silent
!addincludedir "${__FILEDIR__}/../nsis"
!include "LogicLib.nsh"
!include "runner-github.nsh"
!include "runner-local.nsh"

Section
  Call Runner_SetLocal
  FileOpen $0 "$EXEDIR\local-mode.txt" w
  FileWrite $0 "$runner_mode"
  FileClose $0
SectionEnd
