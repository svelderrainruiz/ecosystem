; GitHub runner mode (ARCH-7, INST-REQ-034, 066). Mirrors installer/runners.py register_github.
; The address is the one the user typed; there is no default. The token is never shown: no DetailPrint of it.
Var runner_mode

; The mode page calls it before each choice, so going back and choosing again is not mistaken for a second forge.
Function Runner_Clear
  StrCpy $runner_mode ""
FunctionEnd

Function Runner_SetGithub
  ${If} $runner_mode == "gitlab"
    MessageBox MB_OK|MB_ICONSTOP "This PC already serves a GitLab runner; it can serve only one forge." /SD IDOK
    Abort
  ${EndIf}
  StrCpy $runner_mode "github"
FunctionEnd
