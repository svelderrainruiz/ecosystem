; Tree_Remove (SL-23, issue #115): remove a file, a link or a whole folder tree below the product folder WITHOUT ever entering a link.
; Why: NSIS RMDir with the recursive switch follows a directory junction and deletes the files it points to (measured on real Windows 11, probe P1),
; and the uninstaller runs elevated. So no recursive RMDir is left in installer/nsis (tests/test_installer_sl23.py pins it); every tree goes through here.
; Use: Push "<path below the product folder>" (for example "program"), then Call un.Tree_Remove (Tree_Remove on the install side). The path is
; relative to TREE_ROOT, so every Delete and RMDir below is textually inside the footprint folder (python3 -m installer.footprint check sees it).
; The path must name the entry itself: an empty path, or one that ends in a backslash, is refused. That is a defensive rule, not a measured need:
; GUEST7A measured that RemoveDirectoryW answers the same for a directory link with and without a trailing backslash.
; The result is in $2: 1 when the path, or anything below it, is still there (or the path was refused); 0 when it is gone (a path that is not there at all is gone). $2 is the only register
; it changes: Tree_Remove saves $R0, $R1, $R2, $R4 and $tree_depth on entry and restores them on exit.
; Rules, for every entry found: its reparse-point flag is read first (FileFunc GetFileAttributes reads the entry itself and never follows it; MEASURED
; on a real guest, GUEST7A: it answers 1 for a junction and a directory symbolic link, a dangling one too, and 1 for a file symbolic link). A link is
; never entered. A directory link is removed with the Win32 call RemoveDirectoryW (System plugin), given the path WITHOUT a trailing backslash. READ in
; the Microsoft documentation: it removes the junction or the directory symbolic link itself, not its target. MEASURED (GUEST7A, and the real uninstaller
; in GUEST7B): it removes a directory link whose target is full, empty or gone, and the target stays.
; The plain NSIS RMDir is not used on a link. READ in the NSIS source (v3.10, util.c line 282): it appends a backslash to the path before it calls
; RemoveDirectory; that is true and proves nothing about links. MEASURED (GUEST7A): the plain RMDir also removes only a directory link, never its target,
; but that is not documented and was seen on one Windows build, so RemoveDirectoryW stays (a decision) and the plain RMDir is a possible fallback only.
; A file link is removed with Delete (MEASURED, GUEST7A: it removes a file symbolic link, the target stays, and it does nothing to a directory link).
; A real folder is walked and then removed with RMDir (never the recursive switch) once it is empty; a file is deleted. A removal that fails leaves
; the entry there: the answer is 1 and the walk never goes into it. A System call pushes one value, the result or the word error: READ in the System
; plugin source (System.c lines 403 to 437), not observed on its own; a failed junction removal in GUEST7B (case U8) left the later siblings deleted.
; A path that is not there is gone, nothing is deleted: GetFileAttributes sets the error flag for it, so a failed FIRST flag read is
; checked with IfFileExists (READ in FileFunc.nsh, NSIS 3.10, lines 1231 to 1232 and 1318 to 1320; not measured on Windows). Any other failure is a leftover: an error or empty answer of the flag on an entry that exists, a folder that cannot be listed (a readable folder always lists "." first), a
; folder below level 24 (the path passed in is level 1; it is not entered).
; One source for both sides: the macro defines Tree_Remove and Tree_Walk under the prefix it is given ("un." for the uninstaller).
!ifndef TREE_NSH
!define TREE_NSH
; The install-side copy has no caller yet, and the guest harness includes uninstall.nsh alone (without elevate.nsh, which also disables 6010).
!pragma warning disable 6010
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!insertmacro GetFileAttributes
!insertmacro un.GetFileAttributes

!define TREE_ROOT $APPDATA\EcosystemRunner
Var tree_depth

!macro Tree_Define P
Function ${P}Tree_Remove
  Exch $R0
  Push $R1
  Push $R2
  Push $R4
  Push $tree_depth
  StrCpy $2 1
  StrCmp $R0 "" remove_done
  StrCpy $R1 $R0 1 -1
  StrCmp $R1 "\" remove_done
  Push $R0
  StrCpy $tree_depth 1
  Call ${P}Tree_Walk
remove_done:
  Pop $tree_depth
  Pop $R4
  Pop $R2
  Pop $R1
  Pop $R0
FunctionEnd

Function ${P}Tree_Walk
  Pop $R0
  ClearErrors
  ${${P}GetFileAttributes} "${TREE_ROOT}\$R0" "REPARSE_POINT" $R4
  IfErrors walk_noattr
  StrCmp $R4 "1" walk_link
  StrCmp $R4 "0" 0 walk_left
  IfFileExists "${TREE_ROOT}\$R0\*.*" walk_dir
  Delete "${TREE_ROOT}\$R0"
  Goto walk_check
walk_link:
  ClearErrors
  ${${P}GetFileAttributes} "${TREE_ROOT}\$R0" "DIRECTORY" $R4
  IfErrors walk_left
  StrCmp $R4 "1" walk_link_dir
  StrCmp $R4 "0" 0 walk_left
  Delete "${TREE_ROOT}\$R0"
  Goto walk_check
walk_link_dir:
  System::Call 'kernel32::RemoveDirectoryW(w "${TREE_ROOT}\$R0") i .s'
  Pop $R4
  Goto walk_check
walk_dir:
  ${If} $tree_depth > 24
    Goto walk_left
  ${EndIf}
  FindFirst $R1 $R2 "${TREE_ROOT}\$R0\*.*"
  StrCmp $R2 "" walk_left
walk_next:
  StrCmp $R2 "" walk_end
  StrCmp $R2 "." walk_skip
  StrCmp $R2 ".." walk_skip
  Push $R0
  Push $R1
  Push "$R0\$R2"
  IntOp $tree_depth $tree_depth + 1
  Call ${P}Tree_Walk
  IntOp $tree_depth $tree_depth - 1
  Pop $R1
  Pop $R0
walk_skip:
  FindNext $R1 $R2
  Goto walk_next
walk_end:
  FindClose $R1
  RMDir "${TREE_ROOT}\$R0"
walk_check:
  StrCpy $2 0
  IfFileExists "${TREE_ROOT}\$R0" 0 walk_done
  Goto walk_left
walk_noattr:
  IfFileExists "${TREE_ROOT}\$R0" walk_left
  StrCpy $2 0
  Goto walk_done
walk_left:
  StrCpy $2 1
walk_done:
FunctionEnd
!macroend

!insertmacro Tree_Define "un."
!insertmacro Tree_Define ""
!endif
