; Update and repair (ARCH-8, INST-REQ-038 to 042). This file is authoritative on Windows; installer/update.py is the Python reference model it follows
; (the same order, the same names: program, backup, service.json, installer-state.json) and the host tests use for the shape of the logic.
; Only the program files are replaced (038); configuration, logs, registration, keys and the state file stay until the state file is
; rewritten last (039). A different major version, or a version newer than this installer, is refused (exit 41). The only rollback promise is the one below (041).
; Order of an update (040): lock, backup, stop (confirmed), swap, lock, start, health check, restore on any failure. A service that is not
; confirmed stopped never gets its files swapped. Exit codes are in installer/footprint.json: 41 major-version-mismatch, 42 update-restored,
; 43 update-not-applied, 44 restore-failed, 45 state-invalid.
; Detection reads installer-state.json after elevation (the folder is closed to standard users): no file means a first install (Install_Footprint, unchanged),
; an equal version means repair (042), an older installed version means update. No schema input is used to choose.
Var upd_mode
Var upd_line
Var upd_old
Var upd_hay
Var upd_needle
Var upd_pos
Var upd_ver
Var upd_ok
Var upd_online
Var upd_svc
Var upd_msg
Var upd_code
Var upd_i
Var upd_n
Var upd_c
Var upd_k
Var upd_t
Var upd_acc
Var upd_parts
Var upd_a0
Var upd_a1
Var upd_a2
Var upd_b0
Var upd_b1
Var upd_b2
Var upd_fval
Var upd_fhas
Var upd_json
Var upd_h

; One ending for every refusal: say what, set the footprint.json exit code, stop. $upd_msg and $upd_code are set by the caller.
Function Update_Stop
  MessageBox MB_OK|MB_ICONSTOP "$upd_msg" /SD IDOK
  SetErrorLevel $upd_code
  Quit
FunctionEnd

Function Update_NotApplied
  StrCpy $upd_code 43
  Call Update_Stop
FunctionEnd

; $upd_pos = position of $upd_needle in $upd_hay, or -1. Clobbers $R2 to $R5.
Function Update_Find
  StrLen $R2 $upd_needle
  StrLen $R3 $upd_hay
  StrCpy $upd_pos 0
  find_loop:
  IntOp $R4 $upd_pos + $R2
  IntCmp $R4 $R3 find_try find_try find_none
  find_try:
  StrCpy $R5 $upd_hay $R2 $upd_pos
  StrCmpS $R5 $upd_needle find_done
  IntOp $upd_pos $upd_pos + 1
  Goto find_loop
  find_none:
  StrCpy $upd_pos -1
  find_done:
FunctionEnd

; $upd_ver = a version. $upd_ok = 1 and $upd_b0, $upd_b1, $upd_b2 = its numbers when it is exactly three plain numbers (no sign, no leading zero), else 0.
Function Update_Parse
  StrCpy $upd_ok 0
  StrCpy $upd_parts 0
  StrCpy $upd_acc ""
  StrCpy $upd_i 0
  StrLen $upd_n $upd_ver
  parse_loop:
  IntCmp $upd_i $upd_n parse_end parse_char
  parse_char:
  StrCpy $upd_c $upd_ver 1 $upd_i
  IntOp $upd_i $upd_i + 1
  StrCmp $upd_c "." parse_dot
  StrCpy $upd_k 0
  digit_loop:
  StrCpy $upd_t "0123456789" 1 $upd_k
  StrCmpS $upd_t $upd_c parse_digit
  IntOp $upd_k $upd_k + 1
  IntCmp $upd_k 10 parse_bad digit_loop parse_bad
  parse_digit:
  StrCpy $upd_acc "$upd_acc$upd_c"
  Goto parse_loop
  parse_dot:
  Call Update_Part
  StrCmp $upd_k "bad" parse_bad
  Goto parse_loop
  parse_end:
  Call Update_Part
  StrCmp $upd_k "bad" parse_bad
  StrCmp $upd_parts "3" 0 parse_bad
  StrCpy $upd_ok 1
  parse_bad:
FunctionEnd

; Closes one number of the version: not empty, no leading zero, not a fourth. $upd_k = "bad" when it is wrong.
Function Update_Part
  StrCpy $upd_k "ok"
  StrCmp $upd_acc "" part_bad
  StrCpy $upd_t $upd_acc 1
  StrCmp $upd_t "0" 0 part_store
  StrCmp $upd_acc "0" part_store part_bad
  part_store:
  StrCmp $upd_parts "0" 0 part_one
  StrCpy $upd_b0 $upd_acc
  Goto part_next
  part_one:
  StrCmp $upd_parts "1" 0 part_two
  StrCpy $upd_b1 $upd_acc
  Goto part_next
  part_two:
  StrCmp $upd_parts "2" 0 part_bad
  StrCpy $upd_b2 $upd_acc
  part_next:
  IntOp $upd_parts $upd_parts + 1
  StrCpy $upd_acc ""
  Return
  part_bad:
  StrCpy $upd_k "bad"
FunctionEnd

; $upd_ok = 0 unless $R3 is one character of $R5, compared case-sensitively (StrCmpS: \b is an escape, \B is not). Clobbers $R4 and $R7.
Function Update_OneOf
  StrCpy $R4 0
  oneof_loop:
  StrCpy $R7 $R5 1 $R4
  StrCmp $R7 "" oneof_bad
  IntOp $R4 $R4 + 1
  StrCmpS $R3 $R7 oneof_done oneof_loop
  oneof_bad:
  StrCpy $upd_ok 0
  oneof_done:
FunctionEnd

; Finds the string value after $upd_needle (for example '"mode": "') in $upd_line: $upd_fhas = 1 and $upd_fval = the text up to the next quote.
; #228: Update_WriteState copies that text back verbatim, so it must be a valid JSON string body, else $upd_ok = 0 and detection refuses it
; before any change. Every backslash must start \\ \/ \b \f \n \r \t or \u and four hex digits, and no raw control character may appear. A
; lone backslash at the end means the quote that ended the value was escaped (\"), so the real value goes on past it: refused too.
Function Update_Field
  StrCpy $upd_fhas 0
  StrCpy $upd_fval ""
  StrCpy $upd_ok 1
  StrCpy $upd_hay $upd_line
  Call Update_Find
  StrCmp $upd_pos "-1" field_done
  StrLen $R6 $upd_needle
  IntOp $R7 $upd_pos + $R6
  StrCpy $upd_hay $upd_line "" $R7
  StrCpy $upd_needle '"'
  Call Update_Find
  StrCmp $upd_pos "-1" field_done
  StrCpy $upd_fval $upd_hay $upd_pos
  StrCpy $upd_fhas 1
  StrCpy $R4 1
  field_control:
  IntFmt $R5 "%c" $R4
  ${StrStr} $R3 $upd_fval $R5
  StrCmp $R3 "" 0 field_bad
  IntOp $R4 $R4 + 1
  IntCmp $R4 32 0 field_control
  StrCpy $R2 0
  field_char:
  StrCpy $R3 $upd_fval 1 $R2
  StrCmp $R3 "" field_done
  IntOp $R2 $R2 + 1
  StrCmpS $R3 '\' 0 field_char
  StrCpy $R3 $upd_fval 1 $R2
  IntOp $R2 $R2 + 1
  StrCpy $R5 '\/bfnrtu'
  Call Update_OneOf
  StrCmpS $R3 "u" 0 field_char
  StrCpy $R6 4
  field_hex:
  StrCpy $R3 $upd_fval 1 $R2
  IntOp $R2 $R2 + 1
  StrCpy $R5 "0123456789abcdefABCDEF"
  Call Update_OneOf
  IntOp $R6 $R6 - 1
  IntCmp $R6 0 field_char field_char field_hex
  field_bad:
  StrCpy $upd_ok 0
  field_done:
FunctionEnd

; The state file is one line. $upd_old = installed version. A file that cannot be read, whose first line fills the 1023 character FileRead buffer
; (it would be cut), lacks "schema_version": 1 followed by a comma or a closing brace, holds a version that is not three plain numbers, or
; whose forge_address or mode could not be copied back as valid JSON (#228, Update_Field) is damaged: refused (exit 45), nothing changed.
Function Update_ReadState
  ClearErrors
  FileOpen $upd_h "$APPDATA\EcosystemRunner\installer-state.json" r
  IfErrors state_bad
  FileRead $upd_h $upd_line 1023
  FileClose $upd_h
  StrLen $R6 $upd_line
  IntCmp $R6 1023 state_bad state_ok state_bad
  state_ok:
  StrCpy $upd_hay $upd_line
  StrCpy $upd_needle '"schema_version": 1'
  Call Update_Find
  StrCmp $upd_pos "-1" state_bad
  StrLen $R6 $upd_needle
  IntOp $R6 $upd_pos + $R6
  StrCpy $R7 $upd_line 1 $R6
  StrCmp $R7 "," schema_ok
  StrCmp $R7 "}" schema_ok state_bad
  schema_ok:
  StrCpy $upd_needle '"forge_address": "'
  Call Update_Field
  StrCmp $upd_ok "0" state_bad
  StrCpy $upd_needle '"mode": "'
  Call Update_Field
  StrCmp $upd_ok "0" state_bad
  StrCpy $upd_needle '"installer_version": "'
  Call Update_Field
  StrCmp $upd_fhas "1" 0 state_bad
  StrCpy $upd_old $upd_fval
  StrCpy $upd_ver $upd_old
  Call Update_Parse
  StrCmp $upd_ok "1" state_good
  state_bad:
  StrCpy $upd_msg "The installer state file is damaged; nothing was changed."
  StrCpy $upd_code 45
  Call Update_Stop
  state_good:
  StrCpy $upd_a0 $upd_b0
  StrCpy $upd_a1 $upd_b1
  StrCpy $upd_a2 $upd_b2
FunctionEnd

; The mode page is for a fresh install: an update or a repair keeps the mode of the installed runner and never asks for it (Abort skips the page).
Function Page_mode_Pre
  ${If} $upd_mode == "update"
  ${OrIf} $upd_mode == "repair"
    Abort
  ${EndIf}
  Call Page_mode
FunctionEnd

; Reads the installed version, then compares it with this installer: another major version or a newer installed version is refused (exit 41,
; update.py update_available), the same version is repair, an older one is update. $upd_mode = fresh when there is no state file or this
; process is not elevated yet (the install section runs this again after the elevation).
Function Update_Detect
  StrCpy $upd_mode "fresh"
  Call Elevate_IsAdmin
  ${If} $elev_isadmin == 0
    Return
  ${EndIf}
  SetShellVarContext all
  IfFileExists "$APPDATA\EcosystemRunner\installer-state.json" 0 detect_done
  Call Update_ReadState
  StrCpy $upd_ver "${INSTALLER_VERSION}"
  Call Update_Parse
  ${If} $upd_ok == 0
    StrCpy $upd_msg "This installer has no valid version; nothing was changed."
    StrCpy $upd_code 41
    Call Update_Stop
  ${EndIf}
  ${If} $upd_a0 != $upd_b0
    StrCpy $upd_msg "The installed version $upd_old and this installer (${INSTALLER_VERSION}) have different major versions; nothing was changed."
    StrCpy $upd_code 41
    Call Update_Stop
  ${EndIf}
  StrCpy $upd_mode "repair"
  ${If} $upd_a1 < $upd_b1
    StrCpy $upd_mode "update"
  ${ElseIf} $upd_a1 > $upd_b1
    StrCpy $upd_mode "newer"
  ${ElseIf} $upd_a2 < $upd_b2
    StrCpy $upd_mode "update"
  ${ElseIf} $upd_a2 > $upd_b2
    StrCpy $upd_mode "newer"
  ${EndIf}
  ${If} $upd_mode == "newer"
    StrCpy $upd_msg "The installed version $upd_old is newer than this installer (${INSTALLER_VERSION}); nothing was changed."
    StrCpy $upd_code 41
    Call Update_Stop
  ${EndIf}
  detect_done:
FunctionEnd

; INST-REQ-040, forge modes: the runner also showing online at the forge is the hook of the runner payload's CLI contract (SL-17, open design #32).
; Not filled yet: a forge mode answers "not-checked" and the health check passes on the service state alone. The local mode has no runner: online.
Function Update_RunnerOnline
  StrCpy $upd_online "yes"
  ${If} $upd_svc == 1
    StrCpy $upd_online "not-checked"
  ${EndIf}
FunctionEnd

; $upd_svc = 1 when this install has a runner service: the mode file names a forge, or there is a runner.exe. Plain substring tests, NSIS has no JSON parser.
Function Update_ReadMode
  StrCpy $upd_svc 0
  IfFileExists "$APPDATA\EcosystemRunner\program\runner.exe" 0 mode_file
  StrCpy $upd_svc 1
  mode_file:
  ClearErrors
  FileOpen $upd_h "$APPDATA\EcosystemRunner\runner-mode.json" r
  IfErrors mode_done
  FileRead $upd_h $upd_hay
  FileClose $upd_h
  StrCpy $upd_needle "github"
  Call Update_Find
  StrCmp $upd_pos "-1" 0 mode_forge
  StrCpy $upd_needle "gitlab"
  Call Update_Find
  StrCmp $upd_pos "-1" mode_done
  mode_forge:
  StrCpy $upd_svc 1
  mode_done:
FunctionEnd

; Folder and service definition to the backup folder. Any failure removes the half-made backup and nothing else was touched ($upd_ok = 0).
; service.json records the one service this installer creates (name, account, start type); a missing service is recreated from that definition.
; SL-23b (#124): every tree is removed with Tree_Remove (tree.nsh), never the recursive RMDir, which follows a junction. Tree_Remove changes only $2 (1 = left over);
; no caller here holds $2 across it. An old backup that cannot be cleared stops the update before anything is copied (fail closed, exit 43); the other removals
; of the backup are best effort and leave one update-backup-cleanup line in the log; the restore retries its removal of program like a failed copy.
Function Update_Backup
  StrCpy $upd_ok 0
  IfFileExists "$APPDATA\EcosystemRunner\backup\complete" 0 backup_fresh
  Call Update_RestoreFiles
  ${If} $upd_ok == 0
    Call Update_RestoreFailed
  ${EndIf}
  StrCpy $upd_ok 0
  backup_fresh:
  StrCpy $upd_msg ""
  Push "backup"
  Call Tree_Remove
  ${If} $2 == 1
    Goto backup_done
  ${EndIf}
  ClearErrors
  CreateDirectory "$APPDATA\EcosystemRunner\backup"
  IfErrors backup_done
  CopyFiles /SILENT "$APPDATA\EcosystemRunner\program\*.*" "$APPDATA\EcosystemRunner\backup\program"
  IfErrors backup_done
  IfFileExists "$APPDATA\EcosystemRunner\backup\program\runner.exe" 0 backup_done
  ClearErrors
  FileOpen $upd_h "$APPDATA\EcosystemRunner\backup\service.json" w
  IfErrors backup_service_failed
  FileWrite $upd_h '{"name": "EcosystemRunner", "account": "NT SERVICE\\EcosystemRunner", "start": "auto"}$\r$\n'
  FileClose $upd_h
  IfErrors backup_service_failed
  ; SL-23b part B (#135): the marker is written last, so only a finished backup is ever trusted as the way back
  ClearErrors
  FileOpen $upd_h "$APPDATA\EcosystemRunner\backup\complete" w
  IfErrors backup_marker_failed
  FileClose $upd_h
  IfErrors backup_marker_failed
  StrCpy $upd_ok 1
  Return
  backup_service_failed:
  StrCpy $upd_msg "write backup\service.json"
  Goto backup_done
  backup_marker_failed:
  StrCpy $upd_msg "write backup\complete"
  backup_done:
  ${If} $upd_ok == 0
    Push "backup"
    Call Tree_Remove
    ${If} $2 == 1
      Push "update-backup-cleanup"
      Push "remove backup folder"
      Push "0"
      Call LogStep
    ${EndIf}
    ${If} $upd_msg != ""
      Push $upd_msg
      Call Install_StateFailed
    ${EndIf}
    Push "update-backup"
    Push "CopyFiles program"
    Push "1"
    Call LogStep
  ${EndIf}
FunctionEnd

; The swap: the one program file, written only after the stop was confirmed. SetOverwrite try: a failed write sets the error flag; with on or
; ifdiff NSIS shows Abort/Retry/Ignore, which a silent installer answers with Abort (exit 2) before IfErrors runs, so no restore would happen.
Function Update_Swap
  StrCpy $upd_ok 0
  !ifdef RUNNER_PAYLOAD
    CreateDirectory "$APPDATA\EcosystemRunner\program"
    SetOverwrite try
    StrCpy $R8 0
    StrCpy $R9 1000
    swap_try:
    ClearErrors
    File "/oname=$APPDATA\EcosystemRunner\program\runner.exe" "${RUNNER_PAYLOAD}"
    IfErrors swap_failed
    StrCpy $upd_ok 1
    Goto swap_done
    swap_failed:
    IntOp $R8 $R8 + 1
    IntCmp $R8 6 swap_done swap_wait swap_done
    swap_wait:
    Push "update-swap-retry"
    Push "swap program file"
    Push "0"
    Call LogStep
    Sleep $R9
    ${If} $R9 < 8000
      IntOp $R9 $R9 * 2
    ${EndIf}
    Goto swap_try
  !else
    Goto swap_done
  !endif
  swap_done:
FunctionEnd

; Starts the service (a missing one is created first) and waits for RUNNING. $winsys_ok = 1 when it runs.
Function Update_StartOrCreate
  Call Winsys_QueryState
  ${If} $winsys_state == "GONE"
    Call Winsys_CreateService
  ${EndIf}
  Call Winsys_StartAndWait
FunctionEnd

; Lock, start and health check after a swap. $upd_ok = 1 when the service is healthy.
Function Update_StartAndCheck
  StrCpy $upd_ok 0
  Call Winsys_FolderLock
  Call Update_StartOrCreate
  ${If} $winsys_ok == 1
    Call Winsys_Health
    ${If} $winsys_ok == 1
      Call Update_RunnerOnline
      StrCpy $upd_ok 1
    ${EndIf}
  ${EndIf}
FunctionEnd

; Puts the backed-up program files back (041: that is all it promises). The stop comes first and is confirmed; a failure at any point keeps the
; backup folder and ends with exit 44. Success ends with exit 42 and the one promised sentence.
Function Update_RestoreFiles
  StrCpy $upd_ok 0
  Call Winsys_StopAndWait
  ${If} $winsys_ok == 1
    StrCpy $R8 0
    StrCpy $R9 1000
    restore_try:
    ClearErrors
    Push "program"
    Call Tree_Remove
    StrCmp $2 1 restore_failed
    ClearErrors
    CopyFiles /SILENT "$APPDATA\EcosystemRunner\backup\program\*.*" "$APPDATA\EcosystemRunner\program"
    IfErrors restore_failed
    Goto restore_copied
    restore_failed:
    IntOp $R8 $R8 + 1
    IntCmp $R8 6 restore_done restore_wait restore_done
    restore_wait:
    Push "update-restore-retry"
    Push "restore program files"
    Push "0"
    Call LogStep
    Sleep $R9
    ${If} $R9 < 8000
      IntOp $R9 $R9 * 2
    ${EndIf}
    Goto restore_try
    restore_copied:
    IfFileExists "$APPDATA\EcosystemRunner\program\runner.exe" 0 restore_done
    Call Update_StartAndCheck
  ${EndIf}
  restore_done:
FunctionEnd

; Ends the run when the restore failed: the backup folder is kept untouched (exit 44).
Function Update_RestoreFailed
  Push "update-restore"
  Push "restore program files"
  Push "1"
  Call LogStep
  StrCpy $upd_msg "The previous program files could not be restored. The backup folder $APPDATA\EcosystemRunner\backup was kept."
  StrCpy $upd_code 44
  Call Update_Stop
FunctionEnd

Function Update_Restore
  Call Update_RestoreFiles
  ${If} $upd_ok == 0
    Call Update_RestoreFailed
  ${EndIf}
  Push "update-restore"
  Push "restore program files"
  Push "0"
  Call LogStep
  StrCpy $upd_msg "previous program files restored"
  StrCpy $upd_code 42
  Call Update_Stop
FunctionEnd

; The state file is rewritten last, whole, from the known fields (never from a truncated read): the new version, and the mode and forge address of
; the old file when it had them, in the key order and spacing of update.py write_state (json.dumps with sorted keys, then a line feed).
Function Update_WriteState
  StrCpy $upd_json "{"
  StrCpy $upd_needle '"forge_address": "'
  Call Update_Field
  ${If} $upd_fhas == 1
    StrCpy $upd_json '$upd_json"forge_address": "$upd_fval", '
  ${EndIf}
  StrCpy $upd_json '$upd_json"installer_version": "${INSTALLER_VERSION}", '
  StrCpy $upd_needle '"mode": "'
  Call Update_Field
  ${If} $upd_fhas == 1
    StrCpy $upd_json '$upd_json"mode": "$upd_fval", '
  ${EndIf}
  StrCpy $upd_json '$upd_json"schema_version": 1}'
  ClearErrors
  FileOpen $upd_h "$APPDATA\EcosystemRunner\installer-state.json" w
  IfErrors write_failed
  FileWrite $upd_h "$upd_json$\n"
  FileClose $upd_h
  IfErrors write_failed
  Return
  write_failed:
  Push "write installer-state.json"
  Call Install_StateFailed
FunctionEnd

; The uninstall entry and uninstaller, recreated by a repair and kept current by an update (042).
Function Update_WriteEntry
  ClearErrors
  WriteUninstaller "$APPDATA\EcosystemRunner\uninstall.exe"
  IfErrors 0 uninstaller_ready
  Call Install_UninstallerFailed
  uninstaller_ready:
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner" "DisplayName" "Ecosystem Runner"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner" "DisplayVersion" "${INSTALLER_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner" "UninstallString" '"$APPDATA\EcosystemRunner\uninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner" "QuietUninstallString" '"$APPDATA\EcosystemRunner\uninstall.exe" /S'
FunctionEnd

Function Update_Apply
  Call Winsys_Gate
  SetShellVarContext all
  SetRegView 64
  Call Winsys_FolderCheck
  Call Winsys_FolderLock
  ${IfNot} ${Silent}
    MessageBox MB_YESNO|MB_ICONQUESTION "Update Ecosystem Runner from version $upd_old to ${INSTALLER_VERSION}? The program files are replaced; configuration, logs and keys stay." /SD IDYES IDYES update_go
    StrCpy $upd_msg "The update was declined; nothing was changed."
    Call Update_NotApplied
  ${EndIf}
  update_go:
  Call Update_ReadMode
  ${If} $upd_svc == 1
    Call Update_Backup
    ${If} $upd_ok == 0
      StrCpy $upd_msg "The backup could not be made; nothing was changed."
      Call Update_NotApplied
    ${EndIf}
    Call Winsys_StopAndWait
    ${If} $winsys_ok == 0
      Push "backup"
      Call Tree_Remove
      ${If} $2 == 1
        Push "update-backup-cleanup"
        Push "remove backup folder"
        Push "0"
        Call LogStep
      ${EndIf}
      StrCpy $upd_msg "The service could not be confirmed stopped; nothing was changed."
      Call Update_NotApplied
    ${EndIf}
    Call Update_Swap
    ${If} $upd_ok == 1
      Call Update_StartAndCheck
    ${EndIf}
    ${If} $upd_ok == 0
      Push "update-swap"
      Push "swap, start or health check"
      Push "1"
      Call LogStep
      Call Update_Restore
    ${EndIf}
  ${EndIf}
  ; The marker goes first: a backup whose removal then fails is stale and the next run removes it instead of restoring it over a good program
  Delete "$APPDATA\EcosystemRunner\backup\complete"
  Call Update_WriteState
  Call Update_WriteEntry
  Push "backup"
  Call Tree_Remove
  ${If} $2 == 1
    Push "update-backup-cleanup"
    Push "remove backup folder"
    Push "0"
    Call LogStep
  ${EndIf}
  Call Licence_WriteRecord
  Call Image_Pull
FunctionEnd

; Update and repair end like a first install: the licence record (a failed write exits 37), then the pinned image pull (a failed pull exits 46 and
; does not undo the swap: program and service are consistent, a repair retries the pull). The restore path exits 42 before it and calls neither.
; Repair: the same installer in the same version. It stops a service that exists (confirmed), rewrites the program file every time (SetOverwrite try),
; recreates a missing service and the uninstall entry, rewrites the state file, and never creates a key or registers (042, 083).
Function Update_Repair
  Call Winsys_Gate
  SetShellVarContext all
  SetRegView 64
  Call Winsys_FolderCheck
  Call Winsys_FolderLock
  Call Update_ReadMode
  ${If} $upd_svc == 1
    Call Winsys_StopAndWait
    ${If} $winsys_ok == 0
      StrCpy $upd_msg "The service could not be confirmed stopped; nothing was changed."
      Call Update_NotApplied
    ${EndIf}
    Call Update_Swap
    ${If} $upd_ok == 0
      Push "repair-swap"
      Push "File runner.exe"
      Push "1"
      Call LogStep
      Call Update_StartOrCreate
      StrCpy $upd_msg "The program file could not be repaired: repair stopped."
      Call Update_NotApplied
    ${EndIf}
    Call Update_StartAndCheck
    ${If} $upd_ok == 0
      Push "repair-health"
      Push "service did not run"
      Push "1"
      Call LogStep
      StrCpy $upd_msg "The service did not run after the repair: repair stopped."
      Call Update_NotApplied
    ${EndIf}
  ${EndIf}
  Call Update_WriteState
  Call Update_WriteEntry
  Call Licence_WriteRecord
  Call Image_Pull
FunctionEnd

; The one entry of the install section: a first install runs the install flow unchanged, an update or a repair runs its own.
Function Update_Route
  Call Update_Detect
  ${If} $upd_mode == "update"
    Call Update_Apply
  ${ElseIf} $upd_mode == "repair"
    Call Update_Repair
  ${Else}
    Call Install_Footprint
  ${EndIf}
FunctionEnd
