@echo OFF
setlocal EnableDelayedExpansion

call "%VS140COMNTOOLS%..\..\VC\bin\amd64\vcvars64.bat"

@echo OFF
setlocal EnableDelayedExpansion

for %%I in (%SOURCE_INDEXES%) do (
  clang-cl.exe /c !COMPILER_OPTIONS_%%I! !SOURCE_FILE_%%I! /Fo!OBJECT_FILE_%%I!
  if errorlevel 1 goto :FAIL
)

clang-cl.exe %OBJECT_FILES% /Fe%EXECUTABLE_FILE% /link /SUBSYSTEM:WINDOWS /ENTRY:mainCRTStartup %LINKER_OPTIONS%
if errorlevel 1 goto :FAIL
goto :END

:FAIL
echo FAILED
exit /B 1

:END
exit /B 0
