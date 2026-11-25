; Guest harness: writes the real uninstaller of uninstall.nsh (SL-6) so a Windows guest can run it. Not part of the installer; built by pack.py.
Unicode true
RequestExecutionLevel admin
SilentInstall silent
!addincludedir "${__FILEDIR__}/../nsis"
!include "uninstall.nsh"

Section
  WriteUninstaller "$EXEDIR\uninstall-guest.exe"
SectionEnd
