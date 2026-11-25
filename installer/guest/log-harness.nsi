; Guest harness: runs the real log.nsh (SL-7) in a Windows guest. Not part of the installer; built by pack.py.
Unicode true
RequestExecutionLevel admin
SilentInstall silent
!addincludedir "${__FILEDIR__}/../nsis"
!include "log.nsh"

Section
  Call Log_InitPaths
  SetShellVarContext all
  CreateDirectory "$APPDATA\EcosystemRunner"
  Push "guest-step-one"
  Push "harness-command-one"
  Push "0"
  Call LogStep
  Push "guest-step-two"
  Push "harness-command-two"
  Push "7"
  Call LogStep
  StrCpy $0 'A"B'
  StrCpy $1 'A\Q'
  Push $0
  Push $1
  Push "31"
  Call LogStep
SectionEnd
