; GENERATED from installer/schema.json by `python -m installer.schema generate`; do not edit (drift is checked in CI).
; The pages and macros are wired in by later slices; until then their functions are unreferenced.
!pragma warning disable 6010
!include "LogicLib.nsh"
!include "nsDialogs.nsh"
!include "FileFunc.nsh"
!include "StrFunc.nsh"
${StrStr}
${StrCase}

Var in_mode
Var in_install_dir
Var in_work_dir
Var in_github_url
Var in_gitlab_url
Var in_partner_id
Var in_allow_list
Var in_http_proxy
Var in_dns_servers
Var in_labview_version
Var in_image_variant
Var in_image_year
Var in_ni_licence_held
Var in_engine_licence_accepted
Var in_github_token
Var in_gitlab_token
Var in_registry_password
Var ctl_mode_local
Var ctl_mode_github
Var ctl_mode_gitlab
Var ctl_install_dir
Var ctl_work_dir
Var ctl_github_url
Var ctl_gitlab_url
Var ctl_partner_id
Var ctl_allow_list
Var ctl_http_proxy
Var ctl_dns_servers
Var ctl_labview_version
Var ctl_image_variant
Var ctl_image_year
Var ctl_ni_licence_held
Var ctl_engine_licence_accepted
Var ctl_github_token
Var ctl_gitlab_token
Var ctl_registry_password
Var vs_c
Var vs_name
Var vs_kind
; 1 in the elevated copy that got its answers from the first window (Carried_Detect, elevate.nsh): the pages those answers are for are skipped.
Var carried

; The command line is read by ONE reader, installer/nsis/cmdline.nsh (Cmdline_Begin, Cmdline_Next, Cmdline_Get).
!macro ParseSilentKeys
  Push "/MODE="
  Call Cmdline_Get
  Pop $in_mode
  Push "/INSTALL_DIR="
  Call Cmdline_Get
  Pop $in_install_dir
  Push "/WORK_DIR="
  Call Cmdline_Get
  Pop $in_work_dir
  Push "/GITHUB_URL="
  Call Cmdline_Get
  Pop $in_github_url
  Push "/GITLAB_URL="
  Call Cmdline_Get
  Pop $in_gitlab_url
  Push "/PARTNER_ID="
  Call Cmdline_Get
  Pop $in_partner_id
  Push "/ALLOW_LIST="
  Call Cmdline_Get
  Pop $in_allow_list
  Push "/HTTP_PROXY="
  Call Cmdline_Get
  Pop $in_http_proxy
  Push "/DNS_SERVERS="
  Call Cmdline_Get
  Pop $in_dns_servers
  Push "/LABVIEW_VERSION="
  Call Cmdline_Get
  Pop $in_labview_version
  Push "/IMAGE_VARIANT="
  Call Cmdline_Get
  Pop $in_image_variant
  Push "/IMAGE_YEAR="
  Call Cmdline_Get
  Pop $in_image_year
  Push "/NI_LICENCE_HELD="
  Call Cmdline_Get
  Pop $in_ni_licence_held
  Push "/ENGINE_LICENCE_ACCEPTED="
  Call Cmdline_Get
  Pop $in_engine_licence_accepted
!macroend

; Exit 50 (#136): NSIS keeps at most 1023 characters of $CMDLINE and cuts the rest without a word, so a line of 1023 or more may have lost a key.
; This is the first command-line check, before the secret refusal. It logs fixed words only (the log is appended to only when it already exists) and writes nothing else.
!macro RefuseLongCommandLine
  StrLen $vs_c $CMDLINE
  ${If} $vs_c >= 1023
    Call Log_InitPaths
    StrCpy $LogExistingOnly 1
    Push "cmdline-too-long"
    Push "command-line"
    Push "50"
    Call LogStep
    SetErrorLevel 50
    Quit
  ${EndIf}
!macroend

; INST-REQ-023, 075, 098: a secret on the command line, in a file or on standard input is a typed exit.
; Both command-line loops read the parameters through the one reader, never $CMDLINE: $CMDLINE starts with the program path, and a dash, a slash or a secret-looking word in that path is not an option.
; Refuse_Pass is ONE pass over the words the reader gives after Cmdline_Begin or Cmdline_BeginRaw: the one copy of the refusal rules.
Function Refuse_Pass
  ${Do}
    Call Cmdline_Next
    ${If} ${Errors}
      ${ExitDo}
    ${EndIf}
    StrCpy $R2 $cl_name 1
    ${If} $cl_tok == "-"
      SetErrorLevel 33
      Quit
    ${ElseIf} $R2 == "/"
      ${StrCase} $R3 $cl_name "U"
      ${If} $R3 == "/SECRETFILE"
        SetErrorLevel 33
        Quit
      ${EndIf}
      ${If} $R3 == "/SECRETS"
        SetErrorLevel 33
        Quit
      ${EndIf}
      ${If} $R3 == "/SECRETSTDIN"
        SetErrorLevel 33
        Quit
      ${EndIf}
      ${If} $R3 == "/STDIN"
        SetErrorLevel 33
        Quit
      ${EndIf}
      ${StrStr} $R4 $R3 "TOKEN"
      ${If} $R4 != ""
        SetErrorLevel 32
        Quit
      ${EndIf}
      ${StrStr} $R4 $R3 "SECRET"
      ${If} $R4 != ""
        SetErrorLevel 32
        Quit
      ${EndIf}
      ${StrStr} $R4 $R3 "PASSW"
      ${If} $R4 != ""
        SetErrorLevel 32
        Quit
      ${EndIf}
      ${StrStr} $R4 $R3 "PASSPHRASE"
      ${If} $R4 != ""
        SetErrorLevel 32
        Quit
      ${EndIf}
      ${StrStr} $R4 $R3 "KEY"
      ${If} $R4 != ""
        SetErrorLevel 32
        Quit
      ${EndIf}
      ${StrStr} $R4 $R3 "CREDENTIAL"
      ${If} $R4 != ""
        SetErrorLevel 32
        Quit
      ${EndIf}
    ${EndIf}
  ${Loop}
  ClearErrors
FunctionEnd

; An unclosed double quote hides every later word from the quote-aware pass, so the words are read twice: grouped by quotes, then RAW (a quote opens no group).
!macro RefuseSecretOptions
  Call Cmdline_Begin
  Call Refuse_Pass
  Call Cmdline_BeginRaw
  Call Refuse_Pass
!macroend

; One value at a time: $R0 in, $R9 out (empty = good). Control characters other than tab, CR and LF are not looked for.
Function Val_Line
  StrCpy $R9 ""
  StrLen $R2 $R0
  StrCpy $R3 0
  StrCpy $R4 0
  ${Do}
    ${If} $R3 >= $R2
      ${ExitDo}
    ${EndIf}
    StrCpy $R1 $R0 1 $R3
    ${If} $R1 == "$\t"
    ${OrIf} $R1 == "$\r"
    ${OrIf} $R1 == "$\n"
    StrCpy $R9 "must be on one line"
    Return
    ${EndIf}
    ${If} $R1 != " "
      StrCpy $R4 1
    ${EndIf}
    IntOp $R3 $R3 + 1
  ${Loop}
  ${If} $R4 == 0
    StrCpy $R9 "must not be blank"
  ${EndIf}
FunctionEnd

Function Val_NoQuote
  StrCpy $R9 ""
  StrCpy $R5 '"'
  ${StrStr} $R1 $R0 $R5
  ${If} $R1 != ""
    StrCpy $R9 "must not contain a double quote"
  ${EndIf}
FunctionEnd

Function Val_NoBad
  StrCpy $R9 ""
  ${StrStr} $R1 $R0 " "
  ${If} $R1 != ""
    StrCpy $R9 "must not hold a space, quote, backslash or control character"
    Return
  ${EndIf}
  ${StrStr} $R1 $R0 "$\t"
  ${If} $R1 != ""
    StrCpy $R9 "must not hold a space, quote, backslash or control character"
    Return
  ${EndIf}
  ${StrStr} $R1 $R0 "$\r"
  ${If} $R1 != ""
    StrCpy $R9 "must not hold a space, quote, backslash or control character"
    Return
  ${EndIf}
  ${StrStr} $R1 $R0 "$\n"
  ${If} $R1 != ""
    StrCpy $R9 "must not hold a space, quote, backslash or control character"
    Return
  ${EndIf}
  StrCpy $R5 '"'
  ${StrStr} $R1 $R0 $R5
  ${If} $R1 != ""
    StrCpy $R9 "must not hold a space, quote, backslash or control character"
    Return
  ${EndIf}
  ${StrStr} $R1 $R0 "'"
  ${If} $R1 != ""
    StrCpy $R9 "must not hold a space, quote, backslash or control character"
    Return
  ${EndIf}
  StrCpy $R5 "`"
  ${StrStr} $R1 $R0 $R5
  ${If} $R1 != ""
    StrCpy $R9 "must not hold a space, quote, backslash or control character"
    Return
  ${EndIf}
  ${StrStr} $R1 $R0 "\"
  ${If} $R1 != ""
    StrCpy $R9 "must not hold a space, quote, backslash or control character"
    Return
  ${EndIf}
FunctionEnd

Function Val_Http
  StrCpy $R9 ""
  StrCpy $R1 $R0 8
  ${If} $R1 S== "https://"
    StrCpy $R2 8
  ${Else}
    StrCpy $R1 $R0 7
    ${If} $R1 S== "http://"
      StrCpy $R2 7
    ${Else}
      StrCpy $R9 "must start with http:// or https://"
      Return
    ${EndIf}
  ${EndIf}
  StrCpy $R1 $R0 1 $R2
  ${If} $R1 == ""
  ${OrIf} $R1 == "/"
  ${OrIf} $R1 == " "
  ${OrIf} $R1 == "$\t"
  ${OrIf} $R1 == "$\r"
  ${OrIf} $R1 == "$\n"
    StrCpy $R9 "needs a host after the scheme"
  ${EndIf}
FunctionEnd

; https only, a host, no user name or password, no brackets, an optional port of one to five digits (the same rule as installer.schema._https_problem).
Function Val_Https
  Call Val_NoBad
  ${If} $R9 != ""
    Return
  ${EndIf}
  StrCpy $R1 $R0 8
  ${If} $R1 != "https://"
    StrCpy $R9 "must start with https://"
    Return
  ${EndIf}
  StrLen $R2 $R0
  StrCpy $R3 8
  StrCpy $R5 ""
  ${Do}
    ${If} $R3 >= $R2
      ${ExitDo}
    ${EndIf}
    StrCpy $R1 $R0 1 $R3
    ${If} $R1 == "/"
    ${OrIf} $R1 == "?"
    ${OrIf} $R1 == "#"
      ${ExitDo}
    ${EndIf}
    StrCpy $R5 "$R5$R1"
    IntOp $R3 $R3 + 1
  ${Loop}
  ${If} $R5 == ""
    StrCpy $R9 "needs a host after https://"
    Return
  ${EndIf}
  ${StrStr} $R4 $R5 "@"
  ${If} $R4 != ""
    StrCpy $R9 "must be a plain host name: no user name, password or brackets"
    Return
  ${EndIf}
  ${StrStr} $R4 $R5 "["
  ${If} $R4 != ""
    StrCpy $R9 "must be a plain host name: no user name, password or brackets"
    Return
  ${EndIf}
  ${StrStr} $R4 $R5 "]"
  ${If} $R4 != ""
    StrCpy $R9 "must be a plain host name: no user name, password or brackets"
    Return
  ${EndIf}
  StrCpy $R1 $R5 1
  ${If} $R1 == ":"
    StrCpy $R9 "needs a host after https://"
    Return
  ${EndIf}
  ${StrStr} $R4 $R5 ":"
  ${If} $R4 != ""
    StrCpy $R6 $R4 "" 1
    StrLen $R7 $R6
    ${If} $R7 == 0
    ${OrIf} $R7 > 5
      StrCpy $R9 "has a port that is not one to five digits"
      Return
    ${EndIf}
    StrCpy $R3 0
    ${Do}
      ${If} $R3 >= $R7
        ${ExitDo}
      ${EndIf}
      StrCpy $R1 $R6 1 $R3
      ${StrStr} $R4 "0123456789" $R1
      ${If} $R4 == ""
        StrCpy $R9 "has a port that is not one to five digits"
        Return
      ${EndIf}
      IntOp $R3 $R3 + 1
    ${Loop}
  ${EndIf}
FunctionEnd

Function Val_List
  StrCpy $R9 ""
  StrLen $R2 $R0
  StrCpy $R3 0
  StrCpy $R4 0
  ${Do}
    ${If} $R3 >= $R2
      ${ExitDo}
    ${EndIf}
    StrCpy $R1 $R0 1 $R3
    ${If} $R1 == ","
      ${If} $R4 == 0
        StrCpy $R9 "is a comma separated list with an empty item"
        Return
      ${EndIf}
      StrCpy $R4 0
    ${ElseIf} $R1 != " "
      StrCpy $R4 1
    ${EndIf}
    IntOp $R3 $R3 + 1
  ${Loop}
  ${If} $R4 == 0
    StrCpy $R9 "is a comma separated list with an empty item"
  ${EndIf}
FunctionEnd

Function Check_install_dir
  StrCpy $R0 $in_install_dir
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  Call Val_NoQuote
FunctionEnd

Function Check_work_dir
  StrCpy $R0 $in_work_dir
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  Call Val_NoQuote
FunctionEnd

Function Check_github_url
  StrCpy $R0 $in_github_url
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  Call Val_Https
FunctionEnd

Function Check_gitlab_url
  StrCpy $R0 $in_gitlab_url
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  Call Val_Https
FunctionEnd

Function Check_partner_id
  StrCpy $R0 $in_partner_id
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  Call Val_NoQuote
FunctionEnd

Function Check_allow_list
  StrCpy $R0 $in_allow_list
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  Call Val_List
FunctionEnd

Function Check_http_proxy
  StrCpy $R0 $in_http_proxy
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  Call Val_Http
FunctionEnd

Function Check_dns_servers
  StrCpy $R0 $in_dns_servers
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  Call Val_List
FunctionEnd

Function Check_labview_version
  StrCpy $R0 $in_labview_version
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  Call Val_NoQuote
FunctionEnd

Function Check_image_variant
  StrCpy $R0 $in_image_variant
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  ${StrCase} $R1 $R0 "L"
  ${If} $R1 == "windows"
    StrCpy $in_image_variant "windows"
  ${ElseIf} $R1 == "linux"
    StrCpy $in_image_variant "linux"
  ${Else}
    StrCpy $R9 "must be one of windows, linux"
  ${EndIf}
FunctionEnd

Function Check_image_year
  StrCpy $R0 $in_image_year
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  ${StrCase} $R1 $R0 "L"
  ${If} $R1 == "2026q3"
    StrCpy $in_image_year "2026q3"
  ${ElseIf} $R1 == "2026q1patch2"
    StrCpy $in_image_year "2026q1patch2"
  ${ElseIf} $R1 == "2026q1patch1"
    StrCpy $in_image_year "2026q1patch1"
  ${ElseIf} $R1 == "2026q1"
    StrCpy $in_image_year "2026q1"
  ${ElseIf} $R1 == "2025q3patch1"
    StrCpy $in_image_year "2025q3patch1"
  ${ElseIf} $R1 == "2025q3"
    StrCpy $in_image_year "2025q3"
  ${Else}
    StrCpy $R9 "must be one of 2026q3, 2026q1patch2, 2026q1patch1, 2026q1, 2025q3patch1, 2025q3"
  ${EndIf}
FunctionEnd

Function Check_ni_licence_held
  StrCpy $R0 $in_ni_licence_held
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  ${StrCase} $R1 $R0 "L"
  ${If} $R1 == "yes"
    StrCpy $in_ni_licence_held "yes"
  ${ElseIf} $R1 == "no"
    StrCpy $in_ni_licence_held "no"
  ${Else}
    StrCpy $R9 "must be one of yes, no"
  ${EndIf}
FunctionEnd

Function Check_engine_licence_accepted
  StrCpy $R0 $in_engine_licence_accepted
  Call Val_Line
  ${If} $R9 != ""
    Return
  ${EndIf}
  ${StrCase} $R1 $R0 "L"
  ${If} $R1 == "yes"
    StrCpy $in_engine_licence_accepted "yes"
  ${ElseIf} $R1 == "no"
    StrCpy $in_engine_licence_accepted "no"
  ${Else}
    StrCpy $R9 "must be one of yes, no"
  ${EndIf}
FunctionEnd

Function Check_github_token
  StrCpy $R0 $in_github_token
  Call Val_NoBad
FunctionEnd

Function Check_gitlab_token
  StrCpy $R0 $in_gitlab_token
  Call Val_NoBad
FunctionEnd

Function Check_registry_password
  StrCpy $R0 $in_registry_password
  Call Val_NoBad
FunctionEnd

Function Check_together
  StrCpy $R9 ""
  ${If} $in_image_variant == ""
  ${AndIf} $in_image_year != ""
    StrCpy $R9 "Choose both the NI docker image container type and version, or neither"
  ${ElseIf} $in_image_variant != ""
  ${AndIf} $in_image_year == ""
    StrCpy $R9 "Choose both the NI docker image container type and version, or neither"
  ${EndIf}
FunctionEnd

Function Image_Known
  StrCpy $R9 ""
  ${If} $in_image_variant == ""
    Return
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q3"
    Return
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q1patch2"
    Return
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q1patch1"
    Return
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q1"
    Return
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q3"
    Return
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q1patch2"
    Return
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q1patch1"
    Return
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q1"
    Return
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2025q3patch1"
    Return
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2025q3"
    Return
  ${EndIf}
  StrCpy $R9 "This NI docker image container type and version are not in the pinned list"
FunctionEnd

Function Image_Ref
  StrCpy $R8 ""
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q3"
    StrCpy $R8 "docker.io/nationalinstruments/labview@sha256:ae1894bbba666c1f89ebcfad491713d9ed049b24448a53aaeeacec8556377524"
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q1patch2"
    StrCpy $R8 "docker.io/nationalinstruments/labview@sha256:d44465ad15415150d36221017ce54ca3d9f15db2e1cbf3227fee3e0f7e97f13c"
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q1patch1"
    StrCpy $R8 "docker.io/nationalinstruments/labview@sha256:d834446e486690f4f8a8dede779950e3396e87152849560f5544060bffd91890"
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q1"
    StrCpy $R8 "docker.io/nationalinstruments/labview@sha256:57c453dabd2ff0185ce718d88704921bb82eb83189f4049205ed9b4da7df7bcd"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q3"
    StrCpy $R8 "docker.io/nationalinstruments/labview@sha256:b09fe6328707cac6ef3bde3402dee92d7e6382edb2ec75995c3276e9ab6de7f0"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q1patch2"
    StrCpy $R8 "docker.io/nationalinstruments/labview@sha256:c6484cf4d66a14355bd3195849c090573f413ed355c429c8cc0752fee589b28c"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q1patch1"
    StrCpy $R8 "docker.io/nationalinstruments/labview@sha256:c9cb4e6d9caddffcba11538f29b4189cca98747f87db348b5fd30065551f573b"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q1"
    StrCpy $R8 "docker.io/nationalinstruments/labview@sha256:597ba99260c0511475e27c04f13dd06f2f57e8ce7d3ee6c1ca289020b1f8c426"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2025q3patch1"
    StrCpy $R8 "docker.io/nationalinstruments/labview@sha256:8f20f27dd87abf460e619cece97cc0d19db5f9cb446496340ead3d1531517577"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2025q3"
    StrCpy $R8 "docker.io/nationalinstruments/labview@sha256:9938561c6460841674f9b1871d8562242f51fe9fb72a2c39c66608491edf429c"
  ${EndIf}
FunctionEnd

; Exit 30 for a bad value and 31 for an unknown key, after the step is logged with the key NAME only; nothing is written before them.
Function Silent_Bad
  Pop $R0
  Pop $R1
  Push $R0
  Call Carried_Box
  Push $R1
  Push $R0
  Push "30"
  Call LogStep
  SetErrorLevel 30
  Quit
FunctionEnd

; Reads the parameters, not the program path (see RefuseSecretOptions).
; The first check is the quote: a command line that ends inside a double quote hides what follows from every key check, so it exits 30. The log holds fixed words, never the
; swallowed text (it may be a secret).
!macro ValidateSilentKeys
  Call Cmdline_EndsInQuote
  Pop $vs_c
  ${If} $vs_c == 1
    Push "bad-value"
    Push "command-line"
    Call Silent_Bad
  ${EndIf}
  Call Cmdline_Begin
  ${Do}
    Call Cmdline_Next
    ${If} ${Errors}
      ${ExitDo}
    ${EndIf}
    StrCpy $vs_c $cl_name 1
    ${If} $vs_c == "/"
      ${StrCase} $vs_name $cl_name "U"
      StrCpy $vs_kind ""
      ${If} $vs_name == "/S"
      ${OrIf} $vs_name == "/D"
      ${OrIf} $vs_name == "/NCRC"
      ${OrIf} $vs_name == "/ELEVATED"
      ${OrIf} $vs_name == "/SIGNER"
        StrCpy $vs_kind pass
      ${ElseIf} $vs_name == "/MODE"
      ${OrIf} $vs_name == "/INSTALL_DIR"
      ${OrIf} $vs_name == "/WORK_DIR"
      ${OrIf} $vs_name == "/GITHUB_URL"
      ${OrIf} $vs_name == "/GITLAB_URL"
      ${OrIf} $vs_name == "/PARTNER_ID"
      ${OrIf} $vs_name == "/ALLOW_LIST"
      ${OrIf} $vs_name == "/HTTP_PROXY"
      ${OrIf} $vs_name == "/DNS_SERVERS"
      ${OrIf} $vs_name == "/LABVIEW_VERSION"
      ${OrIf} $vs_name == "/IMAGE_VARIANT"
      ${OrIf} $vs_name == "/IMAGE_YEAR"
      ${OrIf} $vs_name == "/NI_LICENCE_HELD"
      ${OrIf} $vs_name == "/ENGINE_LICENCE_ACCEPTED"
        StrCpy $vs_kind key
      ${EndIf}
      ${If} $vs_kind == ""
        Push "$vs_name"
        Call Carried_Box
        Push "unknown-key"
        Push "$vs_name"
        Push "31"
        Call LogStep
        SetErrorLevel 31
        Quit
      ${EndIf}
      ${If} $vs_kind == "key"
      ${AndIf} $cl_val == ""
        Push "bad-value"
        Push "$vs_name"
        Call Silent_Bad
      ${EndIf}
    ${EndIf}
  ${Loop}
  ClearErrors
  ${If} $in_install_dir != ""
    Call Check_install_dir
    ${If} $R9 != ""
      Push "install_dir"
      Push "/INSTALL_DIR"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_work_dir != ""
    Call Check_work_dir
    ${If} $R9 != ""
      Push "work_dir"
      Push "/WORK_DIR"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_github_url != ""
    Call Check_github_url
    ${If} $R9 != ""
      Push "github_url"
      Push "/GITHUB_URL"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_gitlab_url != ""
    Call Check_gitlab_url
    ${If} $R9 != ""
      Push "gitlab_url"
      Push "/GITLAB_URL"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_partner_id != ""
    Call Check_partner_id
    ${If} $R9 != ""
      Push "partner_id"
      Push "/PARTNER_ID"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_allow_list != ""
    Call Check_allow_list
    ${If} $R9 != ""
      Push "allow_list"
      Push "/ALLOW_LIST"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_http_proxy != ""
    Call Check_http_proxy
    ${If} $R9 != ""
      Push "http_proxy"
      Push "/HTTP_PROXY"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_dns_servers != ""
    Call Check_dns_servers
    ${If} $R9 != ""
      Push "dns_servers"
      Push "/DNS_SERVERS"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_labview_version != ""
    Call Check_labview_version
    ${If} $R9 != ""
      Push "labview_version"
      Push "/LABVIEW_VERSION"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_image_variant != ""
    Call Check_image_variant
    ${If} $R9 != ""
      Push "image_variant"
      Push "/IMAGE_VARIANT"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_image_year != ""
    Call Check_image_year
    ${If} $R9 != ""
      Push "image_year"
      Push "/IMAGE_YEAR"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_ni_licence_held != ""
    Call Check_ni_licence_held
    ${If} $R9 != ""
      Push "ni_licence_held"
      Push "/NI_LICENCE_HELD"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  ${If} $in_engine_licence_accepted != ""
    Call Check_engine_licence_accepted
    ${If} $R9 != ""
      Push "engine_licence_accepted"
      Push "/ENGINE_LICENCE_ACCEPTED"
      Call Silent_Bad
    ${EndIf}
  ${EndIf}
  Call Check_together
  ${If} $R9 != ""
    Push "image_variant"
    Push "/IMAGE_VARIANT"
    Call Silent_Bad
  ${EndIf}
!macroend

; What the first window hands to the elevated copy: the non-blank answers, one token each (Carry_One, elevate.nsh). The three secrets are not here and never go on a command line.
Function Carry_Answers
  ${If} $in_mode != ""
    Push "What this PC does"
    Push "/MODE="
    Push $in_mode
    Call Carry_One
  ${EndIf}
  ${If} $in_install_dir != ""
    Push "Install folder"
    Push "/INSTALL_DIR="
    Push $in_install_dir
    Call Carry_One
  ${EndIf}
  ${If} $in_work_dir != ""
    Push "Work folder"
    Push "/WORK_DIR="
    Push $in_work_dir
    Call Carry_One
  ${EndIf}
  ${If} $in_github_url != ""
    Push "GitHub address"
    Push "/GITHUB_URL="
    Push $in_github_url
    Call Carry_One
  ${EndIf}
  ${If} $in_gitlab_url != ""
    Push "GitLab address"
    Push "/GITLAB_URL="
    Push $in_gitlab_url
    Call Carry_One
  ${EndIf}
  ${If} $in_partner_id != ""
    Push "Partner or organisation ID"
    Push "/PARTNER_ID="
    Push $in_partner_id
    Call Carry_One
  ${EndIf}
  ${If} $in_allow_list != ""
    Push "Allow-list (comma separated)"
    Push "/ALLOW_LIST="
    Push $in_allow_list
    Call Carry_One
  ${EndIf}
  ${If} $in_http_proxy != ""
    Push "Proxy address"
    Push "/HTTP_PROXY="
    Push $in_http_proxy
    Call Carry_One
  ${EndIf}
  ${If} $in_dns_servers != ""
    Push "DNS servers (comma separated)"
    Push "/DNS_SERVERS="
    Push $in_dns_servers
    Call Carry_One
  ${EndIf}
  ${If} $in_labview_version != ""
    Push "LabVIEW version"
    Push "/LABVIEW_VERSION="
    Push $in_labview_version
    Call Carry_One
  ${EndIf}
  ${If} $in_image_variant != ""
    Push "NI docker image container type"
    Push "/IMAGE_VARIANT="
    Push $in_image_variant
    Call Carry_One
  ${EndIf}
  ${If} $in_image_year != ""
    Push "NI docker image version"
    Push "/IMAGE_YEAR="
    Push $in_image_year
    Call Carry_One
  ${EndIf}
  ${If} $in_ni_licence_held != ""
    Push "Yes, we hold a development licence (NI licence conditions)"
    Push "/NI_LICENCE_HELD="
    Push $in_ni_licence_held
    Call Carry_One
  ${EndIf}
  ${If} $in_engine_licence_accepted != ""
    Push "Yes, we accept the container engine licence conditions"
    Push "/ENGINE_LICENCE_ACCEPTED="
    Push $in_engine_licence_accepted
    Call Carry_One
  ${EndIf}
FunctionEnd

Function Page_mode
  ${If} $carried == 1
    Abort
  ${EndIf}
  !insertmacro Dialog_Create
  ${NSD_CreateLabel} 0u 0u 100% 20u "Choose what this PC does: local only (no forge), a GitHub runner or a GitLab runner. Choose one, then select Next."
  ${NSD_CreateFirstRadioButton} 0u 24u 100% 12u "Local only (no forge)"
  Pop $ctl_mode_local
  ${NSD_CreateAdditionalRadioButton} 0u 40u 100% 12u "GitHub runner"
  Pop $ctl_mode_github
  ${NSD_CreateAdditionalRadioButton} 0u 56u 100% 12u "GitLab runner"
  Pop $ctl_mode_gitlab
  nsDialogs::Show
FunctionEnd

Function Page_mode_Leave
  StrCpy $in_mode ""
  ${NSD_GetState} $ctl_mode_local $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $in_mode "local"
  ${EndIf}
  ${NSD_GetState} $ctl_mode_github $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $in_mode "github"
  ${EndIf}
  ${NSD_GetState} $ctl_mode_gitlab $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $in_mode "gitlab"
  ${EndIf}
  ${If} $in_mode == ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "Choose what this PC does, then select Next." /SD IDOK
    Abort
  ${EndIf}
  Call Runner_Clear
  ${If} $in_mode == "local"
    Call Runner_SetLocal
  ${ElseIf} $in_mode == "github"
    Call Runner_SetGithub
  ${ElseIf} $in_mode == "gitlab"
    Call Runner_SetGitlab
  ${EndIf}
FunctionEnd

; Silent run: no key leaves the mode alone; a value that is none of the choices ends with the bad-value exit before anything is written.
Function Mode_FromSilent
  Push "/MODE="
  Call Cmdline_Get
  Pop $0
  ${If} ${Errors}
    Return
  ${EndIf}
  ${StrCase} $in_mode $0 "L"
  ${If} $in_mode == "local"
    Call Runner_SetLocal
    Return
  ${EndIf}
  ${If} $in_mode == "github"
    Call Runner_SetGithub
    Return
  ${EndIf}
  ${If} $in_mode == "gitlab"
    Call Runner_SetGitlab
    Return
  ${EndIf}
  Push "/MODE"
  Call Carried_Box
  Push "mode"
  Push "/MODE"
  Push "30"
  Call LogStep
  SetErrorLevel 30
  Quit
FunctionEnd

Function Page_folders
  ${If} $carried == 1
    Abort
  ${EndIf}
  !insertmacro Dialog_Create
  ${NSD_CreateLabel} 0u 0u 100% 20u "Type an install folder and a work folder. Each typed folder is checked when you select Next; an empty box is skipped."
  ${NSD_CreateLabel} 0u 24u 100% 8u "Install folder"
  ${NSD_CreateText} 0u 33u 100% 12u ""
  Pop $ctl_install_dir
  SendMessage $ctl_install_dir ${EM_LIMITTEXT} 1023 0
  ${NSD_CreateLabel} 0u 48u 100% 8u "Work folder"
  ${NSD_CreateText} 0u 57u 100% 12u ""
  Pop $ctl_work_dir
  SendMessage $ctl_work_dir ${EM_LIMITTEXT} 1023 0
  nsDialogs::Show
FunctionEnd

Function Page_folders_Leave
  ${NSD_GetText} $ctl_install_dir $in_install_dir
  ${NSD_GetText} $ctl_work_dir $in_work_dir
  ${If} $in_install_dir != ""
    Call Check_install_dir
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "Install folder: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
  ${If} $in_work_dir != ""
    Call Check_work_dir
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "Work folder: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
FunctionEnd

Function Page_forge
  ${If} $carried == 1
    Abort
  ${EndIf}
  !insertmacro Dialog_Create
  ${NSD_CreateLabel} 0u 0u 100% 20u "The GitHub or GitLab address (https:// only), the partner or organisation ID and the allow-list. An empty box is skipped."
  ${NSD_CreateLabel} 0u 24u 100% 8u "GitHub address"
  ${NSD_CreateText} 0u 33u 100% 12u ""
  Pop $ctl_github_url
  SendMessage $ctl_github_url ${EM_LIMITTEXT} 1023 0
  ${NSD_CreateLabel} 0u 48u 100% 8u "GitLab address"
  ${NSD_CreateText} 0u 57u 100% 12u ""
  Pop $ctl_gitlab_url
  SendMessage $ctl_gitlab_url ${EM_LIMITTEXT} 1023 0
  ${NSD_CreateLabel} 0u 72u 100% 8u "Partner or organisation ID"
  ${NSD_CreateText} 0u 81u 100% 12u ""
  Pop $ctl_partner_id
  SendMessage $ctl_partner_id ${EM_LIMITTEXT} 1023 0
  ${NSD_CreateLabel} 0u 96u 100% 8u "Allow-list (comma separated)"
  ${NSD_CreateText} 0u 105u 100% 12u ""
  Pop $ctl_allow_list
  SendMessage $ctl_allow_list ${EM_LIMITTEXT} 1023 0
  nsDialogs::Show
FunctionEnd

Function Page_forge_Leave
  ${NSD_GetText} $ctl_github_url $in_github_url
  ${NSD_GetText} $ctl_gitlab_url $in_gitlab_url
  ${NSD_GetText} $ctl_partner_id $in_partner_id
  ${NSD_GetText} $ctl_allow_list $in_allow_list
  ${If} $in_github_url != ""
    Call Check_github_url
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "GitHub address: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
  ${If} $in_gitlab_url != ""
    Call Check_gitlab_url
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "GitLab address: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
  ${If} $in_partner_id != ""
    Call Check_partner_id
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "Partner or organisation ID: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
  ${If} $in_allow_list != ""
    Call Check_allow_list
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "Allow-list (comma separated): $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
FunctionEnd

Function Page_network
  ${If} $carried == 1
    Abort
  ${EndIf}
  !insertmacro Dialog_Create
  ${NSD_CreateLabel} 0u 0u 100% 20u "Only if this PC needs them: a proxy address (http:// or https://) and DNS servers, separated by commas. An empty box is skipped."
  ${NSD_CreateLabel} 0u 24u 100% 8u "Proxy address"
  ${NSD_CreateText} 0u 33u 100% 12u ""
  Pop $ctl_http_proxy
  SendMessage $ctl_http_proxy ${EM_LIMITTEXT} 1023 0
  ${NSD_CreateLabel} 0u 48u 100% 8u "DNS servers (comma separated)"
  ${NSD_CreateText} 0u 57u 100% 12u ""
  Pop $ctl_dns_servers
  SendMessage $ctl_dns_servers ${EM_LIMITTEXT} 1023 0
  nsDialogs::Show
FunctionEnd

Function Page_network_Leave
  ${NSD_GetText} $ctl_http_proxy $in_http_proxy
  ${NSD_GetText} $ctl_dns_servers $in_dns_servers
  ${If} $in_http_proxy != ""
    Call Check_http_proxy
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "Proxy address: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
  ${If} $in_dns_servers != ""
    Call Check_dns_servers
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "DNS servers (comma separated): $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
FunctionEnd

Function Page_labview
  ${If} $carried == 1
    Abort
  ${EndIf}
  !insertmacro Dialog_Create
  ${NSD_CreateLabel} 0u 0u 100% 20u "Type the LabVIEW version this PC uses. An empty box is skipped."
  ${NSD_CreateLabel} 0u 24u 100% 8u "LabVIEW version"
  ${NSD_CreateText} 0u 33u 100% 12u ""
  Pop $ctl_labview_version
  SendMessage $ctl_labview_version ${EM_LIMITTEXT} 1023 0
  nsDialogs::Show
FunctionEnd

Function Page_labview_Leave
  ${NSD_GetText} $ctl_labview_version $in_labview_version
  ${If} $in_labview_version != ""
    Call Check_labview_version
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "LabVIEW version: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
FunctionEnd

Function Page_image
  ${If} $carried == 1
    Abort
  ${EndIf}
  !insertmacro Dialog_Create
  ${NSD_CreateLabel} 0u 0u 100% 20u "Choose the container type, then the NI docker image version. The runner uses it; it is pulled at install time. (none) skips it."
  Pop $0
  ${NSD_CreateLabel} 0u 24u 100% 8u "NI docker image container type"
  Pop $0
  ${NSD_CreateDropList} 0u 33u 100% 52u ""
  Pop $ctl_image_variant
  ${NSD_CB_AddString} $ctl_image_variant "(none)"
  ${NSD_CB_AddString} $ctl_image_variant "windows"
  ${NSD_CB_AddString} $ctl_image_variant "linux"
  ${NSD_CreateLabel} 0u 48u 100% 8u "NI docker image version"
  Pop $0
  ${NSD_CreateDropList} 0u 57u 100% 70u ""
  Pop $ctl_image_year
  ; Back from a later page shows the answers again: (none) unless a container type is held, then the versions of that type.
  SendMessage $ctl_image_variant ${CB_SETCURSEL} 0 0
  ${If} $in_image_variant == "windows"
    SendMessage $ctl_image_variant ${CB_SETCURSEL} 1 0
  ${ElseIf} $in_image_variant == "linux"
    SendMessage $ctl_image_variant ${CB_SETCURSEL} 2 0
  ${EndIf}
  Call Image_Fill
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q3"
    SendMessage $ctl_image_year ${CB_SETCURSEL} 0 0
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q1patch2"
    SendMessage $ctl_image_year ${CB_SETCURSEL} 1 0
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q1patch1"
    SendMessage $ctl_image_year ${CB_SETCURSEL} 2 0
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $in_image_year == "2026q1"
    SendMessage $ctl_image_year ${CB_SETCURSEL} 3 0
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q3"
    SendMessage $ctl_image_year ${CB_SETCURSEL} 0 0
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q1patch2"
    SendMessage $ctl_image_year ${CB_SETCURSEL} 1 0
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q1patch1"
    SendMessage $ctl_image_year ${CB_SETCURSEL} 2 0
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2026q1"
    SendMessage $ctl_image_year ${CB_SETCURSEL} 3 0
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2025q3patch1"
    SendMessage $ctl_image_year ${CB_SETCURSEL} 4 0
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $in_image_year == "2025q3"
    SendMessage $ctl_image_year ${CB_SETCURSEL} 5 0
  ${EndIf}
  ${NSD_OnChange} $ctl_image_variant Image_TypeChanged
  nsDialogs::Show
FunctionEnd

; nsDialogs calls this when the container type changes, with the control handle on the stack.
Function Image_TypeChanged
  Pop $0
  Call Image_Fill
FunctionEnd

; The version list: emptied, then the pinned versions of the container type shown, newest first; greyed out for (none).
Function Image_Fill
  ${NSD_GetText} $ctl_image_variant $R1
  SendMessage $ctl_image_year ${CB_RESETCONTENT} 0 0
  EnableWindow $ctl_image_year 0
  ${If} $R1 == "windows"
    EnableWindow $ctl_image_year 1
    ${NSD_CB_AddString} $ctl_image_year "2026 Q3"
    ${NSD_CB_AddString} $ctl_image_year "2026 Q1 patch 2"
    ${NSD_CB_AddString} $ctl_image_year "2026 Q1 patch 1"
    ${NSD_CB_AddString} $ctl_image_year "2026 Q1"
  ${EndIf}
  ${If} $R1 == "linux"
    EnableWindow $ctl_image_year 1
    ${NSD_CB_AddString} $ctl_image_year "2026 Q3"
    ${NSD_CB_AddString} $ctl_image_year "2026 Q1 patch 2"
    ${NSD_CB_AddString} $ctl_image_year "2026 Q1 patch 1"
    ${NSD_CB_AddString} $ctl_image_year "2026 Q1"
    ${NSD_CB_AddString} $ctl_image_year "2025 Q3 patch 1"
    ${NSD_CB_AddString} $ctl_image_year "2025 Q3"
  ${EndIf}
FunctionEnd

Function Page_image_Leave
  ${NSD_GetText} $ctl_image_variant $in_image_variant
  ${If} $in_image_variant == "(none)"
    StrCpy $in_image_variant ""
  ${EndIf}
  ${NSD_GetText} $ctl_image_year $R0
  StrCpy $in_image_year ""
  ${If} $in_image_variant == "windows"
  ${AndIf} $R0 == "2026 Q3"
    StrCpy $in_image_year "2026q3"
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $R0 == "2026 Q1 patch 2"
    StrCpy $in_image_year "2026q1patch2"
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $R0 == "2026 Q1 patch 1"
    StrCpy $in_image_year "2026q1patch1"
  ${EndIf}
  ${If} $in_image_variant == "windows"
  ${AndIf} $R0 == "2026 Q1"
    StrCpy $in_image_year "2026q1"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $R0 == "2026 Q3"
    StrCpy $in_image_year "2026q3"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $R0 == "2026 Q1 patch 2"
    StrCpy $in_image_year "2026q1patch2"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $R0 == "2026 Q1 patch 1"
    StrCpy $in_image_year "2026q1patch1"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $R0 == "2026 Q1"
    StrCpy $in_image_year "2026q1"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $R0 == "2025 Q3 patch 1"
    StrCpy $in_image_year "2025q3patch1"
  ${EndIf}
  ${If} $in_image_variant == "linux"
  ${AndIf} $R0 == "2025 Q3"
    StrCpy $in_image_year "2025q3"
  ${EndIf}
  ${If} $in_image_variant != ""
    Call Check_image_variant
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "NI docker image container type: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
  ${If} $in_image_year != ""
    Call Check_image_year
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "NI docker image version: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
  Call Check_together
  ${If} $R9 != ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "$R9." /SD IDOK
    Abort
  ${EndIf}
  Call Image_Known
  ${If} $R9 != ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "$R9." /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Function Page_licences
  ${If} $carried == 1
    Abort
  ${EndIf}
  ${If} $in_image_variant == ""
    Abort
  ${EndIf}
  !insertmacro Dialog_Create
  ${NSD_CreateLabel} 0u 0u 100% 20u "Shown because an NI docker image was chosen. Tick both licence boxes to continue."
  ${NSD_CreateCheckbox} 0u 24u 100% 12u "Yes, we hold a development licence (NI licence conditions)"
  Pop $ctl_ni_licence_held
  ${NSD_CreateCheckbox} 0u 48u 100% 12u "Yes, we accept the container engine licence conditions"
  Pop $ctl_engine_licence_accepted
  nsDialogs::Show
FunctionEnd

Function Page_licences_Leave
  ${NSD_GetState} $ctl_ni_licence_held $0
  StrCpy $in_ni_licence_held "no"
  ${If} $0 == ${BST_CHECKED}
    StrCpy $in_ni_licence_held "yes"
  ${EndIf}
  ${NSD_GetState} $ctl_engine_licence_accepted $0
  StrCpy $in_engine_licence_accepted "no"
  ${If} $0 == ${BST_CHECKED}
    StrCpy $in_engine_licence_accepted "yes"
  ${EndIf}
  ${If} $in_ni_licence_held != "yes"
  ${OrIf} $in_engine_licence_accepted != "yes"
    MessageBox MB_OK|MB_ICONEXCLAMATION "Tick both licence boxes to continue." /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Function Page_secrets
  !insertmacro Dialog_Create
  ; the elevated copy shows nothing before this page, and Back from the first page ends the installer window: the button is off there
  ${If} $carried == 1
    GetDlgItem $0 $HWNDPARENT 3
    EnableWindow $0 0
  ${EndIf}
  ${NSD_CreateLabel} 0u 0u 100% 20u "Tokens and passwords are typed here only, never on the command line. Fill in only the ones you need; an empty box is skipped."
  ${NSD_CreateLabel} 0u 24u 100% 8u "GitHub registration token"
  ${NSD_CreatePassword} 0u 33u 100% 12u ""
  Pop $ctl_github_token
  SendMessage $ctl_github_token ${EM_LIMITTEXT} 1023 0
  ${NSD_CreateLabel} 0u 48u 100% 8u "GitLab runner token"
  ${NSD_CreatePassword} 0u 57u 100% 12u ""
  Pop $ctl_gitlab_token
  SendMessage $ctl_gitlab_token ${EM_LIMITTEXT} 1023 0
  ${NSD_CreateLabel} 0u 72u 100% 8u "Image registry password"
  ${NSD_CreatePassword} 0u 81u 100% 12u ""
  Pop $ctl_registry_password
  SendMessage $ctl_registry_password ${EM_LIMITTEXT} 1023 0
  nsDialogs::Show
FunctionEnd

Function Page_secrets_Leave
  ${NSD_GetText} $ctl_github_token $in_github_token
  ${NSD_GetText} $ctl_gitlab_token $in_gitlab_token
  ${NSD_GetText} $ctl_registry_password $in_registry_password
  ${If} $in_github_token != ""
    Call Check_github_token
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "GitHub registration token: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
  ${If} $in_gitlab_token != ""
    Call Check_gitlab_token
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "GitLab runner token: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
  ${If} $in_registry_password != ""
    Call Check_registry_password
    ${If} $R9 != ""
      MessageBox MB_OK|MB_ICONEXCLAMATION "Image registry password: $R9." /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}
FunctionEnd
