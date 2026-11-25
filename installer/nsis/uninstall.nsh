; Uninstall (ARCH-9, INST-REQ-043 to 045, 078, 084, 095, 096). Mirrors installer/update.py uninstall and installer/winsys.py. No network is used.
; The uninstaller section at the end calls them (un. prefix). The service is stopped (and waited for) and deleted first, then the folder and the 64-bit registry entry.
; The uninstall entry and the folder are removed here; the service is removed by the same logic. A registration is never reported
; as removed unless the forge confirmed it; otherwise the place at the forge is listed.
; In the folder the contents go first and uninstall.exe only when nothing else is left: a recursive RMDir on the folder would take uninstall.exe
; along with everything else it can reach, even when a locked file keeps the folder (measured on the guest). The uninstall entry goes last.
; SL-23 (issue #115): no tree is removed with the recursive RMDir, which follows a junction and deletes what it points to (probe P1);
; every tree goes through un.Tree_Remove (tree.nsh), which never enters a link.
; What a caller can see (installer/README.md): the registered strings have no switch _?=, so the first stage copies itself to TEMP and returns 0 at
; once, and no exit code of this file reaches that caller; the state is the signal (a leftover keeps the folder and the uninstall entry).
; Only uninstall.exe /S _?=<folder> runs in place, so only then the exit codes are visible; then the running uninstaller stays in the folder.
; This file is included alone by installer/guest/uninstall-harness.nsi, so it brings what it needs.
!include "LogicLib.nsh"
!include "tree.nsh"

Var unelev_isadmin

; The same test as Elevate_IsAdmin in elevate.nsh, under an un. name (uninstaller code may call only un. functions).
Function un.Elevate_IsAdmin
  UserInfo::GetAccountType
  Pop $0
  ${If} $0 == "Admin"
    StrCpy $unelev_isadmin 1
  ${Else}
    StrCpy $unelev_isadmin 0
  ${EndIf}
FunctionEnd

; INST-REQ-078, defence in depth: RequestExecutionLevel user in main.nsi applies to this uninstaller too. A standard user cannot even start the
; installed uninstall.exe (the folder is locked), so this guards the case where it is started anyway. Nothing has been touched at this point.
; Not an administrator: exit code 38 (footprint.json not-elevated); interactive, one message first. No relaunch with runas.
Function un.onInit
  Call un.Elevate_IsAdmin
  ${If} $unelev_isadmin == 0
    SetErrorLevel 38
    ${IfNot} ${Silent}
      MessageBox MB_OK|MB_ICONSTOP "Uninstalling needs administrator rights. Start the uninstall as an administrator." /SD IDOK
    ${EndIf}
    Quit
  ${EndIf}
FunctionEnd

; The one way an uninstall ends when something is left: say what, set the exit code (footprint.json uninstall-stopped, the kind of
; update.UninstallStopped) and stop. It never touches the uninstall entry, so folder and entry stay as the visible state. Each caller says
; what is true for it: most end with "Run the uninstall again."; the one that has already deleted uninstall.exe cannot say that.
Function un.Uninstall_Stopped
  Pop $9
  MessageBox MB_OK|MB_ICONSTOP "Uninstall stopped: $9" /SD IDOK
  SetErrorLevel 40
  Quit
FunctionEnd

; Stop (1061, cannot accept control yet, is retried after 1, 2, 4, 8, 8, 8 s as winsys.STOP_RETRY_SECONDS), then poll sc query until STOPPED
; or 1060 (no such service) for at most 30 polls (winsys.STATE_POLLS), then delete; 0, 1060 and 1072 are fine for the delete. Every other
; result, and nsExec's "error", is a stopped uninstall: nothing else is removed. Results are compared as text.
Function un.Uninstall_RemoveService
  StrCpy $1 0
  StrCpy $2 1000
stop_again:
  nsExec::Exec '"$SYSDIR\sc.exe" stop EcosystemRunner'
  Pop $0
  StrCmp $0 "1062" service_stopped
  StrCmp $0 "1060" service_stopped
  StrCmp $0 "0" wait_stopped
  StrCmp $0 "1061" 0 stop_failed
  ${If} $1 < 6
    IntOp $1 $1 + 1
    Sleep $2
    ${If} $2 < 8000
      IntOp $2 $2 * 2
    ${EndIf}
    Goto stop_again
  ${EndIf}
stop_failed:
  Push "the service could not be stopped (code $0). Run the uninstall again."
  Call un.Uninstall_Stopped
wait_stopped:
  StrCpy $1 0
poll_again:
  nsExec::ExecToStack '"$SYSDIR\sc.exe" query EcosystemRunner'
  Pop $0
  Pop $3
  StrCmp $0 "1060" service_stopped
  StrCmp $0 "0" 0 query_failed
  StrCpy $4 0
scan_state:
  StrCpy $5 $3 7 $4
  StrCmp $5 "STOPPED" service_stopped
  StrCmp $5 "" not_yet
  IntOp $4 $4 + 1
  Goto scan_state
not_yet:
  IntOp $1 $1 + 1
  ${If} $1 < 30
    Sleep 1000
    Goto poll_again
  ${EndIf}
  Push "the service did not stop within 30 seconds. Run the uninstall again."
  Call un.Uninstall_Stopped
query_failed:
  Push "the service state could not be read (code $0). Run the uninstall again."
  Call un.Uninstall_Stopped
service_stopped:
  nsExec::Exec '"$SYSDIR\sc.exe" delete EcosystemRunner'
  Pop $0
  StrCmp $0 "0" delete_done
  StrCmp $0 "1060" delete_done
  StrCmp $0 "1072" delete_done
  Push "the service could not be deleted (code $0). Run the uninstall again."
  Call un.Uninstall_Stopped
delete_done:
FunctionEnd

; Started in place (uninstall.exe /S _?=<folder>) the running file is inside the folder and cannot delete itself: it alone is not a leftover.
; Result in $2: 1 when nothing but the running uninstaller is left, else 0. Started by the registered strings (a copy in TEMP) it is always 0.
Function un.Uninstall_OnlySelfLeft
  StrCpy $2 0
  StrCmp $EXEDIR "$APPDATA\EcosystemRunner" 0 self_done
  StrCpy $2 1
  FindFirst $3 $4 "$APPDATA\EcosystemRunner\*.*"
  ; an empty first name means the folder could not be listed: then nothing proves that only the running uninstaller is left
  StrCmp $4 "" 0 self_next
  StrCpy $2 0
  Return
self_next:
  StrCmp $4 "" self_end
  StrCmp $4 "." self_skip
  StrCmp $4 ".." self_skip
  StrCmp $4 $EXEFILE self_skip
  StrCpy $2 0
  Goto self_end
self_skip:
  FindNext $3 $4
  Goto self_next
self_end:
  FindClose $3
self_done:
FunctionEnd

; Everything in the folder except uninstall.exe, each entry through un.Tree_Remove (a link is removed as a link, never entered).
; Result in $2: 1 when something other than uninstall.exe is still there, else 0. The folder itself is never removed here.
; $5 collects the result of the entries: un.Tree_Remove answers in $2 and keeps $3, $4 and $5.
Function un.Uninstall_ClearFolder
  StrCpy $5 0
  FindFirst $3 $4 "$APPDATA\EcosystemRunner\*.*"
  ; a readable folder always lists "." first: an empty first name means the folder is absent (nothing to clear) or exists but could not be
  ; listed, which is a leftover (fail closed)
  StrCmp $4 "" 0 clear_next
  StrCpy $2 0
  IfFileExists "$APPDATA\EcosystemRunner" 0 clear_return
  StrCpy $2 1
clear_return:
  Return
clear_next:
  StrCmp $4 "" clear_end
  StrCmp $4 "." clear_skip
  StrCmp $4 ".." clear_skip
  StrCmp $4 "uninstall.exe" clear_skip
  Push "$4"
  Call un.Tree_Remove
  StrCmp $2 "1" 0 clear_skip
  StrCpy $5 1
clear_skip:
  FindNext $3 $4
  Goto clear_next
clear_end:
  FindClose $3
  StrCpy $2 $5
FunctionEnd

; Order (INST-REQ-084): everything except uninstall.exe, with up to five retries one second apart (runner.exe may still be mapped); only when
; nothing else is left uninstall.exe, then the folder, and the uninstall entry LAST. While anything else is left uninstall.exe and the entry
; stay and the run ends through un.Uninstall_Stopped (message, exit code 40): folder, uninstall.exe and entry are what a caller sees, and the
; uninstall can be run again. Started in place the running uninstall.exe cannot delete itself; it alone is not a leftover.
; The one edge: uninstall.exe is already deleted but the empty folder still cannot be removed. Nothing can be run again, so the entry is
; removed, the message names the folder to delete by hand, and the exit code is still 40.
Function un.Uninstall_RemoveFiles
  SetShellVarContext all
  SetRegView 64
  ; The folder itself must be a real folder: when it is a link (or its flag cannot be read) nothing is deleted, uninstall.exe and the entry stay.
  IfFileExists "$APPDATA\EcosystemRunner" 0 folder_checked
  ClearErrors
  ${un.GetFileAttributes} "$APPDATA\EcosystemRunner" "REPARSE_POINT" $0
  IfErrors folder_unchecked
  StrCmp $0 "0" folder_checked
  StrCmp $0 "1" 0 folder_unchecked
  Push "$APPDATA\EcosystemRunner is a link (a junction or a symbolic link), not a folder, so nothing was deleted; the uninstall entry was kept and so was uninstall.exe. Remove the link by hand and run the uninstall again."
  Call un.Uninstall_Stopped
folder_unchecked:
  Push "the folder $APPDATA\EcosystemRunner could not be checked for a link, so nothing was deleted; the uninstall entry was kept and so was uninstall.exe. Run the uninstall again."
  Call un.Uninstall_Stopped
folder_checked:
  StrCpy $1 0
remove_again:
  Call un.Uninstall_ClearFolder
  StrCmp $2 "1" try_later
  Delete "$APPDATA\EcosystemRunner\uninstall.exe"
  RMDir "$APPDATA\EcosystemRunner"
  IfFileExists "$APPDATA\EcosystemRunner" 0 folder_gone
  Call un.Uninstall_OnlySelfLeft
  StrCmp $2 "1" folder_gone
try_later:
  ${If} $1 < 5
    IntOp $1 $1 + 1
    Sleep 1000
    Goto remove_again
  ${EndIf}
  ; $2 is 1 here when something other than uninstall.exe is left, 0 when the run got as far as the folder
  StrCmp $2 "1" kept
  IfFileExists "$APPDATA\EcosystemRunner\uninstall.exe" kept folder_stuck
kept:
  Push "the folder could not be removed (a file may still be in use); the uninstall entry was kept and so was uninstall.exe. Run the uninstall again."
  Call un.Uninstall_Stopped
folder_stuck:
  StrCpy $7 "the folder $APPDATA\EcosystemRunner could not be removed and uninstall.exe is already gone, so the uninstall entry was removed too. Delete that folder by hand."
  Goto forget_entry
folder_gone:
  StrCpy $7 ""
forget_entry:
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\EcosystemRunner"
  StrCmp $7 "" all_done
  Push $7
  Call un.Uninstall_Stopped
all_done:
FunctionEnd

Function un.Uninstall_ForgeNote
  MessageBox MB_OK|MB_ICONINFORMATION "Still to do at the forge: delete this runner by hand at the place listed in the uninstall report." /SD IDOK
FunctionEnd

Section "Uninstall"
  Call un.Uninstall_RemoveService
  Call un.Uninstall_RemoveFiles
  Call un.Uninstall_ForgeNote
SectionEnd
