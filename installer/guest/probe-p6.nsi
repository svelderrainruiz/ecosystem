; GUEST7A probe P6: what the read and removal instructions of installer/nsis/tree.nsh do to directory junctions, directory symbolic links and
; file symbolic links. One process is one measurement: probe-p6.exe <OP> <path> (OP is exactly three characters, then one space, then the path).
; The one result line goes to C:\X\g7a\nsis-out.txt; link-probes.ps1 rebuilds the fixture before every call and checks the target afterwards.
; The instructions are the ones the uninstaller uses (FileFunc GetFileAttributes, IfFileExists, RMDir, Delete) next to the raw Win32 calls.
; Not part of the installer; built by pack.py.
Unicode true
RequestExecutionLevel admin
SilentInstall silent
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!insertmacro GetParameters
!insertmacro GetFileName
!insertmacro GetParent
!insertmacro GetFileAttributes

; $R1 is the path under test, $8 the result line. The error flag is cleared before each measured instruction and read right after it.
!macro Flag KEY
  ${If} ${Errors}
    StrCpy $8 "$8 ${KEY}=1"
  ${Else}
    StrCpy $8 "$8 ${KEY}=0"
  ${EndIf}
!macroend
!macro Exists KEY PATH
  ${If} ${FileExists} "${PATH}"
    StrCpy $8 "$8 ${KEY}=Y"
  ${Else}
    StrCpy $8 "$8 ${KEY}=N"
  ${EndIf}
!macroend
!macro Attr KEY ATTR
  ClearErrors
  ${GetFileAttributes} "$R1" "${ATTR}" $0
  ${If} ${Errors}
    StrCpy $8 "$8 ${KEY}=[$0]!err"
  ${Else}
    StrCpy $8 "$8 ${KEY}=[$0]"
  ${EndIf}
  ClearErrors
!macroend
; raw GetFileAttributesW on the text in $4: the value in hex, and GetLastError (kept by the ?e option) when it is INVALID_FILE_ATTRIBUTES
!macro Raw KEY
  System::Call 'kernel32::GetFileAttributesW(w r4)i .r0 ?e'
  Pop $1
  IntFmt $2 "0x%08X" $0
  ${If} $0 = -1
    StrCpy $8 "$8 ${KEY}=$2/lasterr=$1"
  ${Else}
    StrCpy $8 "$8 ${KEY}=$2"
  ${EndIf}
!macroend
; one raw Win32 removal on the text in $4: return value, the NSIS error flag and GetLastError, then whether the link entry is still found
!macro Win32Call FUNC
  ClearErrors
  System::Call 'kernel32::${FUNC}(w r4)i .r0 ?e'
  Pop $1
  StrCpy $8 "$8 ret=$0"
  !insertmacro Flag err
  StrCpy $8 "$8 lasterr=$1"
!macroend

Section
  ${GetParameters} $R9
  StrCpy $R0 $R9 3
  StrCpy $R1 $R9 "" 4
  StrCpy $8 "op=$R0"
  ${If} $R0 == "A1r"
    ; A1 reads: (a) GetFileAttributes macro, (b) IfFileExists, (c) raw GetFileAttributesW with and without a trailing backslash, (d) FindFirst listing
    !insertmacro Attr rp REPARSE_POINT
    !insertmacro Attr dir DIRECTORY
    !insertmacro Attr all ALL
    !insertmacro Exists iffe "$R1"
    !insertmacro Exists iffe_star "$R1\*.*"
    StrCpy $4 "$R1"
    !insertmacro Raw raw
    StrCpy $4 "$R1\"
    !insertmacro Raw raw_bs
    ${GetParent} "$R1" $R2
    ${GetFileName} "$R1" $R3
    StrCpy $5 "N"
    FindFirst $6 $7 "$R2\*.*"
    ${DoWhile} $7 != ""
      ${If} $7 == "$R3"
        StrCpy $5 "Y"
      ${EndIf}
      FindNext $6 $7
    ${Loop}
    FindClose $6
    StrCpy $8 "$8 listed=$5"
  ${ElseIf} $R0 == "A2a"
    ClearErrors
    RMDir "$R1"
    StrCpy $8 "$8 ret=- lasterr=-"
    !insertmacro Flag err
  ${ElseIf} $R0 == "A2b"
    ClearErrors
    Delete "$R1"
    StrCpy $8 "$8 ret=- lasterr=-"
    !insertmacro Flag err
  ${ElseIf} $R0 == "A2c"
    StrCpy $4 "$R1"
    !insertmacro Win32Call RemoveDirectoryW
  ${ElseIf} $R0 == "A2d"
    StrCpy $4 "$R1\"
    !insertmacro Win32Call RemoveDirectoryW
  ${ElseIf} $R0 == "A2e"
    StrCpy $4 "$R1"
    !insertmacro Win32Call DeleteFileW
  ${ElseIf} $R0 == "A3r"
    ; RMDir /r is the one recursive instruction of the probe: it acts only on an entry strictly under the fixture folder, tested on the absolute
    ; form of the path (so a `..` cannot climb out) and run on that same text
    StrCpy $4 "$R1"
    System::Call 'kernel32::GetFullPathNameW(w r4, i ${NSIS_MAX_STRLEN}, w .r2, i 0)i .r0'
    StrLen $5 $2
    StrCpy $3 $2 9
    ${If} $3 == "C:\X\g7a\"
    ${AndIf} $5 > 9
      ClearErrors
      RMDir /r "$2"
      StrCpy $8 "$8 ret=- lasterr=-"
      !insertmacro Flag err
    ${Else}
      StrCpy $8 "$8 ret=- lasterr=- refused=1"
    ${EndIf}
  ${Else}
    StrCpy $8 "$8 unknown-op"
  ${EndIf}
  ${If} $R0 != "A1r"
    !insertmacro Exists iffe "$R1"
  ${EndIf}
  FileOpen $9 "C:\X\g7a\nsis-out.txt" w
  FileWrite $9 "$8"
  FileClose $9
SectionEnd
