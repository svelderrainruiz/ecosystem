; Pull of the pinned NI docker image (SL-16b). The command is fixed: the engine, "pull" and a reference taken from the schema table
; (Image_Ref, repository@digest); no typed text reaches it. Output is not kept. The registry password is not used: a pull that needs
; a login fails with exit 46 (SL-17 designs how the password reaches the engine).
; There is deliberately NO timeout: the engine call shows no progress and an NI docker image pull can take hours, so one constant line is shown first and a
; user who cancels waits until the pull ends. Never add /TIMEOUT: it would kill a pull that is working.
; The engine is never found through the search path: an elevated installer that runs a bare "docker" would run a docker.exe planted in the folder the installer
; was started from. Image_Engine looks for the engine in two fixed places under $PROGRAMFILES64 and answers the absolute path in $R7 (empty when there is none).
; ENGINE_EXE is a compile-time override ONLY for tests (-DENGINE_EXE=<path>); a release build never defines it.
!ifdef ENGINE_EXE
  !ifndef RUNNER_TEST_BUILD
    !error "ENGINE_EXE is a test-only define: add -DRUNNER_TEST_BUILD=1 (a release build never defines it)"
  !endif
!else
  !define ENGINE_EXE ""
!endif

Var ImgRef
Var ImgEngine

Function Image_Engine
  StrCpy $R7 "${ENGINE_EXE}"
  ${If} $R7 != ""
    Return
  ${EndIf}
  IfFileExists "$PROGRAMFILES64\Docker\Docker\resources\bin\docker.exe" desktop
  IfFileExists "$PROGRAMFILES64\Docker\docker.exe" engine
  Return
  desktop:
  StrCpy $R7 "$PROGRAMFILES64\Docker\Docker\resources\bin\docker.exe"
  Return
  engine:
  StrCpy $R7 "$PROGRAMFILES64\Docker\docker.exe"
FunctionEnd

; Trims blanks, CR and LF from both ends of $R1 ($R2 is scratch).
Function Image_Trim
  ${Do}
    StrCpy $R2 $R1 1
    ${If} $R2 == " "
    ${OrIf} $R2 == "$\r"
    ${OrIf} $R2 == "$\n"
      StrCpy $R1 $R1 "" 1
    ${Else}
      ${ExitDo}
    ${EndIf}
  ${Loop}
  ${Do}
    StrCpy $R2 $R1 "" -1
    ${If} $R2 == " "
    ${OrIf} $R2 == "$\r"
    ${OrIf} $R2 == "$\n"
      StrCpy $R1 $R1 -1
    ${Else}
      ${ExitDo}
    ${EndIf}
  ${Loop}
FunctionEnd

; $R1 is the engine's answer to "info --format {{.OSType}}". When it is not the chosen container type, nothing is pulled: the same path as a
; pull failure (exit 46, the installation stays, a repair pulls again).
Function Image_Mode
  Call Image_Trim
  ${StrCase} $R1 $R1 "L"
  ${If} $R1 S!= $in_image_variant
    Push "image-engine-mode"
    Push "engine"
    Push "46"
    Call LogStep
    MessageBox MB_OK|MB_ICONEXCLAMATION "Docker is running $R1 containers, but the NI docker image needs $in_image_variant containers. Switch Docker to $in_image_variant containers and run the installer again to repair." /SD IDOK
    SetErrorLevel 46
    Quit
  ${EndIf}
FunctionEnd

; Last step of the install: the install is complete and removable when this fails.
Function Image_Pull
  Call Licence_Ready
  ${If} $R9 != "1"
    Return
  ${EndIf}
  IfFileExists "$APPDATA\EcosystemRunner\licence-record.json" have_record
  Return
  have_record:
  Call Image_Ref
  StrCpy $ImgRef $R8
  ${If} $ImgRef == ""
    Push "image-not-pinned"
    Push "image"
    Push "36"
    Call LogStep
    SetErrorLevel 36
    Quit
  ${EndIf}
  Call Image_Engine
  StrCpy $ImgEngine $R7
  ${If} $ImgEngine == ""
    Push "image-engine-missing"
    Push "engine"
    Push "46"
    Call LogStep
    MessageBox MB_OK|MB_ICONEXCLAMATION "The container engine was not found. The installation stays: install Docker, then run the installer again to repair." /SD IDOK
    SetErrorLevel 46
    Quit
  ${EndIf}
  ; Docker runs one container mode at a time: an image of the other mode fails with "no matching manifest", so the mode is read first (#159).
  ; A read that fails (no exit code 0) changes nothing: the pull runs and reports its own failure.
  DetailPrint "Checking which container type Docker runs."
  nsExec::ExecToStack '"$ImgEngine" info --format {{.OSType}}'
  Pop $R0
  Pop $R1
  ${If} $R0 == 0
    Call Image_Mode
  ${EndIf}
  DetailPrint "Pulling the NI docker image. This can take a long time; Cancel waits until it ends."
  nsExec::Exec '"$ImgEngine" pull $ImgRef'
  Pop $R0
  ${If} $R0 != 0
    Push "image-pull"
    Push "pull"
    Push "46"
    Call LogStep
    MessageBox MB_OK|MB_ICONEXCLAMATION "The NI docker image could not be pulled. The installation stays: run the installer again to repair." /SD IDOK
    SetErrorLevel 46
    Quit
  ${EndIf}
FunctionEnd
