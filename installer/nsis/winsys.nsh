; Windows system glue (SL-10, INST-REQ-091 to 094, 043). Mirrors installer/winsys.py with the same fixed commands.
; Every function here is the elevated phase only: it refuses (exit code 38) when not administrator, so nothing runs before the prompt.
; No secret is passed on any command line; the config.toml ACL is set by installer/winsys.py restrict_acl.
Function Winsys_Gate
  Call Elevate_IsAdmin
  ${If} $elev_isadmin != 1
    SetErrorLevel 38
    Quit
  ${EndIf}
FunctionEnd

; Best effort: a half-installed service is removed so the next try starts clean.
Function Winsys_Cleanup
  nsExec::Exec '"$SYSDIR\sc.exe" stop EcosystemRunner'
  Pop $0
  nsExec::Exec '"$SYSDIR\sc.exe" delete EcosystemRunner'
  Pop $0
FunctionEnd

Function Winsys_CreateService
  Call Winsys_Gate
  SetShellVarContext all
  SetRegView 64
  nsExec::Exec '"$SYSDIR\sc.exe" create EcosystemRunner binPath= "$APPDATA\EcosystemRunner\program\runner.exe" obj= "NT SERVICE\EcosystemRunner" start= auto'
  Pop $0
  ${If} $0 != 0
    Push "service-create"
    Push "sc.exe create"
    Push $0
    Call LogStep
    SetErrorLevel 3
    Quit
  ${EndIf}
  nsExec::Exec '"$SYSDIR\sc.exe" sidtype EcosystemRunner unrestricted'
  Pop $0
  ${If} $0 != 0
    Push "service-sidtype"
    Push "sc.exe sidtype"
    Push $0
    Call LogStep
    Call Winsys_Cleanup
    SetErrorLevel 3
    Quit
  ${EndIf}
  nsExec::Exec `"$SYSDIR\icacls.exe" "$APPDATA\EcosystemRunner" /grant:r *S-1-5-80-1994812370-2417282942-4224635210-1542273099-3328997366:(OI)(CI)RX`
  Pop $0
  ${If} $0 != 0
    Push "service-grant"
    Push "icacls.exe grant"
    Push $0
    Call LogStep
    Call Winsys_Cleanup
    SetErrorLevel 3
    Quit
  ${EndIf}
  nsExec::Exec '"$SYSDIR\sc.exe" start EcosystemRunner'
  Pop $0
  ${If} $0 == 1069
    Push "service-start"
    Push "sc.exe start"
    Push $0
    Call LogStep
    Call Winsys_Cleanup
    MessageBox MB_OK|MB_ICONSTOP "logon failure: NT SERVICE\EcosystemRunner could not log on as a service." /SD IDOK
    SetErrorLevel 4
    Quit
  ${ElseIf} $0 != 0
  ${AndIf} $0 != 1056
    Push "service-start"
    Push "sc.exe start"
    Push $0
    Call LogStep
    Call Winsys_Cleanup
    SetErrorLevel 3
    Quit
  ${EndIf}
FunctionEnd

; Install folder lock (SL-13, INST-REQ-030). Mirrors installer/winsys.py folder_status, lock_folder and prepare_folder.
; The probe prints absent, fresh (an empty directory), ours (a valid state file) or foreign (a link, an owner that is not SYSTEM or
; Administrators, or anything else); any failure of the probe counts as foreign. $1 gets the first four letters of the answer.
Function Winsys_FolderStatus
  nsExec::ExecToStack `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "$$p='$APPDATA\EcosystemRunner';if(!(Test-Path -LiteralPath $$p)){'absent';exit}$$i=Get-Item -LiteralPath $$p -Force;$$o=(Get-Acl -LiteralPath $$p).GetOwner([Security.Principal.SecurityIdentifier]).Value;if(!$$i.PSIsContainer -or ($$i.Attributes -band 1024) -or ($$o -ne 'S-1-5-18' -and $$o -ne 'S-1-5-32-544')){'foreign';exit}if(@(Get-ChildItem -LiteralPath $$p -Force).Count -eq 0){'fresh';exit}$$s=Join-Path $$p 'installer-state.json';try{$$f=Get-Item -LiteralPath $$s -Force;$$j=Get-Content -LiteralPath $$s -Raw|ConvertFrom-Json;if(!($$f.Attributes -band 1024) -and $$j.schema_version -eq 1 -and $$j.installer_version){'ours';exit}}catch{}'foreign'"`
  Pop $0
  Pop $1
  StrCpy $1 $1 4
  ${If} $0 != 0
    StrCpy $1 "fore"
  ${EndIf}
FunctionEnd

Function Winsys_FolderRefuse
  SetErrorLevel 39
  MessageBox MB_OK|MB_ICONSTOP "The folder $APPDATA\EcosystemRunner already exists and was not created by this installer, or holds a link or a file placed in it before it was locked: nothing was installed. An administrator must delete or rename it first." /SD IDOK
  Abort "The install folder exists and is not ours: installation stopped."
FunctionEnd

; Before the folder is created: a foreign folder is refused.
Function Winsys_FolderCheck
  Call Winsys_Gate
  Call Winsys_FolderStatus
  ${If} $1 != "abse"
  ${AndIf} $1 != "fres"
  ${AndIf} $1 != "ours"
    Call Winsys_FolderRefuse
  ${EndIf}
FunctionEnd

Function Winsys_FolderCreate
  Call Winsys_Gate
  System::Call 'advapi32::ConvertStringSecurityDescriptorToSecurityDescriptorW(w "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", i 1, *p .r1, p 0) i .r0'
  StrCmp $0 0 descriptor_failed
  ; Contrib/System/System.html, "How can I pass structs to functions?" and &l4:
  ; x86-unicode installer (even on 64-bit Windows): DWORD size=12, pointer, BOOL FALSE.
  System::Call '*(&l4, p r1, i 0)p.r2'
  ${If} $2 != 0
    System::Call 'kernel32::CreateDirectoryW(w "$APPDATA\EcosystemRunner", p r2) i .r0'
    System::Free $2
  ${EndIf}
  System::Call 'kernel32::LocalFree(p r1) p'
  StrCmp $2 0 descriptor_failed
  ${If} $0 == 0
    Call Winsys_FolderRefuse
  ${EndIf}
  Return
  descriptor_failed:
    ; Log to installer details, not steps.jsonl in a folder we do not yet own.
    DetailPrint "folder-create: could not prepare the folder security descriptor (exit 2)"
    SetErrorLevel 2
    Abort "The install folder security descriptor could not be prepared: installation stopped."
FunctionEnd

; After the lock: any child, link or foreign owner is found while the folder is already closed to standard users. $1 = empt, clea, owne, link or erro.
Function Winsys_FolderAudit
  nsExec::ExecToStack `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "$$ErrorActionPreference='Stop';$$p='$APPDATA\EcosystemRunner';$$b=0;$$w=0;$$n=0;$$q=New-Object System.Collections.Queue;$$q.Enqueue($$p);while($$q.Count){$$d=$$q.Dequeue();foreach($$c in @(Get-ChildItem -LiteralPath $$d -Force)){$$n++;if($$c.Attributes -band 1024){$$b=1;continue};if(!$$c.PSIsContainer -and $$c.LinkType -eq 'HardLink'){$$b=1};$$o=(Get-Acl -LiteralPath $$c.FullName).GetOwner([Security.Principal.SecurityIdentifier]).Value;if($$o -ne 'S-1-5-18' -and $$o -ne 'S-1-5-32-544'){$$w=1};if($$c.PSIsContainer){$$q.Enqueue($$c.FullName)}}}if($$b){'links'}elseif($$n -eq 0){'empty'}elseif($$w){'owners'}else{'clean'}"`
  Pop $0
  Pop $1
  StrCpy $1 $1 4
  ${If} $0 != 0
    StrCpy $1 "erro"
  ${EndIf}
FunctionEnd

; An older install: the children go to Administrators and take the folder's ACL (the reset never names the folder itself; setowner does, which is fine, it is already Administrators-owned after the lock). No /C: a per-file failure must exit non-zero.
Function Winsys_FolderReset
  nsExec::Exec `"$SYSDIR\icacls.exe" "$APPDATA\EcosystemRunner" /setowner *S-1-5-32-544 /T /L`
  Pop $0
  ${If} $0 != 0
    SetErrorLevel 2
    Abort "The install folder could not be reset: installation stopped."
  ${EndIf}
  nsExec::Exec `"$SYSDIR\icacls.exe" "$APPDATA\EcosystemRunner\*" /reset /T /L`
  Pop $0
  ${If} $0 != 0
    SetErrorLevel 2
    Abort "The install folder could not be reset: installation stopped."
  ${EndIf}
FunctionEnd

; After the folder exists and before any file is written: it must be empty or ours (a folder planted in between is refused), then the ACL,
; then the audit. A fresh folder must still be empty; one that is ours must hold no link, and its children are reset.
Function Winsys_FolderLock
  Call Winsys_Gate
  Call Winsys_FolderStatus
  ${If} $1 != "fres"
  ${AndIf} $1 != "ours"
    Call Winsys_FolderRefuse
  ${EndIf}
  Push $R9
  StrCpy $R9 $1
  nsExec::Exec `"$SYSDIR\icacls.exe" "$APPDATA\EcosystemRunner" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F /grant:r *S-1-5-32-544:(OI)(CI)F`
  Pop $0
  ${If} $0 != 0
    SetErrorLevel 2
    Abort "The install folder could not be locked: installation stopped."
  ${EndIf}
  Call Winsys_FolderAudit
  ${If} $R9 == "fres"
    ${If} $1 != "empt"
      Call Winsys_FolderRefuse
    ${EndIf}
  ${Else}
    ${If} $1 != "clea"
    ${AndIf} $1 != "owne"
      Call Winsys_FolderRefuse
    ${EndIf}
    Call Winsys_FolderReset
    Call Winsys_FolderAudit
    ${If} $1 != "clea"
      Call Winsys_FolderRefuse
    ${EndIf}
  ${EndIf}
  Pop $R9
FunctionEnd

; Install-side service waits (SL-19, INST-REQ-040, 092). The un. copies in uninstall.nsh cannot be called from the installer; the retry and poll numbers
; are the same as winsys.py (STOP_RETRY_SECONDS, STATE_POLLS). $winsys_ok = 1 only when the state was confirmed; every other result is 0.
; They clobber $0 to $5 and set $winsys_code (the last sc.exe result). Winsys_Cleanup is not used by them and is unchanged.
Var winsys_ok
Var winsys_state
Var winsys_code

; $winsys_state = STOPPED, RUNNING, GONE (1060, no such service), OTHER (a pending state) or ERROR (sc.exe itself failed). Scans the text for the first 7-letter state.
Function Winsys_QueryState
  nsExec::ExecToStack '"$SYSDIR\sc.exe" query EcosystemRunner'
  Pop $0
  Pop $3
  StrCpy $winsys_state "ERROR"
  StrCmp $0 "1060" query_gone
  StrCmp $0 "0" 0 query_done
  StrCpy $winsys_state "OTHER"
  StrCpy $4 0
  query_scan:
  StrCpy $5 $3 7 $4
  StrCmp $5 "" query_done
  StrCmpS $5 "STOPPED" query_stopped
  StrCmpS $5 "RUNNING" query_running
  IntOp $4 $4 + 1
  Goto query_scan
  query_stopped:
  StrCpy $winsys_state "STOPPED"
  Goto query_done
  query_running:
  StrCpy $winsys_state "RUNNING"
  Goto query_done
  query_gone:
  StrCpy $winsys_state "GONE"
  query_done:
FunctionEnd

; Stop (1061, cannot accept control yet, is retried after 1, 2, 4, 8, 8, 8 s), then poll sc query up to 30 times until STOPPED or gone. A service that
; is already stopped (1062) or absent (1060) counts as stopped. A stop-pending service that never stops is a failure: its files must not be swapped.
Function Winsys_StopAndWait
  StrCpy $winsys_ok 0
  StrCpy $1 0
  StrCpy $2 1000
  stop_again:
  nsExec::Exec '"$SYSDIR\sc.exe" stop EcosystemRunner'
  Pop $winsys_code
  StrCmp $winsys_code "1062" stop_ok
  StrCmp $winsys_code "1060" stop_ok
  StrCmp $winsys_code "0" stop_poll
  StrCmp $winsys_code "1061" 0 stop_done
  ${If} $1 < 6
    IntOp $1 $1 + 1
    Sleep $2
    ${If} $2 < 8000
      IntOp $2 $2 * 2
    ${EndIf}
    Goto stop_again
  ${EndIf}
  Goto stop_done
  stop_poll:
  StrCpy $1 0
  poll_again:
  Call Winsys_QueryState
  StrCmp $winsys_state "STOPPED" stop_ok
  StrCmp $winsys_state "GONE" stop_ok
  StrCmp $winsys_state "ERROR" stop_done
  IntOp $1 $1 + 1
  ${If} $1 < 30
    Sleep 1000
    Goto poll_again
  ${EndIf}
  Goto stop_done
  stop_ok:
  StrCpy $winsys_ok 1
  stop_done:
FunctionEnd

; Start (0, or 1056 already running), then up to 30 polls for RUNNING. A stopped or missing service after the start is a failure.
Function Winsys_StartAndWait
  StrCpy $winsys_ok 0
  nsExec::Exec '"$SYSDIR\sc.exe" start EcosystemRunner'
  Pop $winsys_code
  StrCmp $winsys_code "0" start_poll
  StrCmp $winsys_code "1056" start_poll
  Goto start_done
  start_poll:
  StrCpy $1 0
  start_again:
  Call Winsys_QueryState
  StrCmp $winsys_state "RUNNING" start_ok
  StrCmp $winsys_state "OTHER" 0 start_done
  IntOp $1 $1 + 1
  ${If} $1 < 30
    Sleep 1000
    Goto start_again
  ${EndIf}
  Goto start_done
  start_ok:
  StrCpy $winsys_ok 1
  start_done:
FunctionEnd

; The health check (INST-REQ-040, update.py HEALTH_SECONDS): RUNNING at every one of 30 polls, one a second. Anything else is unhealthy.
Function Winsys_Health
  StrCpy $winsys_ok 0
  StrCpy $1 0
  health_again:
  Call Winsys_QueryState
  StrCmp $winsys_state "RUNNING" 0 health_done
  IntOp $1 $1 + 1
  ${If} $1 < 30
    Sleep 1000
    Goto health_again
  ${EndIf}
  StrCpy $winsys_ok 1
  health_done:
FunctionEnd
