; GitLab runner mode (ARCH-7, INST-REQ-036, 091 to 094). Mirrors installer/runners.py install_gitlab.
; The install step runs only when already elevated (INST-REQ-091); the service account is the dedicated virtual one
; named in footprint.json. The token is written only to config.toml in the install folder, never displayed.
Function Runner_SetGitlab
  ${If} $runner_mode == "github"
    MessageBox MB_OK|MB_ICONSTOP "This PC already serves a GitHub runner; it can serve only one forge." /SD IDOK
    Abort
  ${EndIf}
  StrCpy $runner_mode "gitlab"
FunctionEnd

Function Runner_GitlabInstallGate
  ${If} $runner_mode == "gitlab"
  ${AndIf} $elev_isadmin == 0
    SetErrorLevel 38
    Quit
  ${EndIf}
FunctionEnd
