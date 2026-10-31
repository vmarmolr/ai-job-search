@echo off
rem Morning job delivery - started by Windows Task Scheduler ("AI Job Search Daily").
rem Runs /daily headless in the repo and logs to daily\logs\.
rem Keep this file CRLF: cmd's goto is unreliable on LF-only batch files.

rem The repo root is this script's parent folder, wherever it was cloned.
cd /d "%~dp0.."

rem Use claude from PATH; fall back to the default per-user install location.
set "CLAUDE=claude"
where claude >nul 2>nul || set "CLAUDE=%USERPROFILE%\.local\bin\claude.exe"

if not exist daily\logs mkdir daily\logs
rem Local page server for the "I applied" checkboxes; exits at once if already running.
start "" /b pythonw daily\server.py
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
if not defined TODAY set TODAY=unknown-date
rem runner.log records every attempt and exit code, so a run that leaves no output still leaves evidence.
>> daily\logs\runner.log echo %DATE% %TIME% start TODAY=%TODAY%

rem Token budget: each phase is a fresh conversation on the cheapest model that does it well, and a
rem phase whose output exists is skipped, so a retry keeps finished work. --setting-sources project skips
rem user plugins, hooks and instructions; --tools keeps the tool list short (ToolSearch reaches connectors).
rem A run can die without a page (API overload, usage limit): try again, up to 3 attempts per day.
set ATTEMPT=0
set RETRY_WAIT_SECONDS=1200
:attempt
set /a ATTEMPT+=1
>> daily\logs\runner.log echo %DATE% %TIME% attempt %ATTEMPT%

set "OUT=daily\%TODAY%"
if exist "%OUT%\index.html" goto delivered
if exist "%OUT%\scrape_done.txt" goto rank
call :phase daily-scrape haiku
if errorlevel 1 goto attempt_end
:rank
if exist "%OUT%\fetch_done.txt" goto cvs
call :phase daily sonnet
if errorlevel 1 goto attempt_end
:cvs
if exist "%OUT%\cvs_done.txt" goto page
call :phase daily-cvs opus
if errorlevel 1 goto attempt_end
:page
call :phase daily-page sonnet
:attempt_end
>> daily\logs\runner.log echo %DATE% %TIME% attempt %ATTEMPT% exit=%ERRORLEVEL%

if exist "daily\%TODAY%\index.html" exit /b 0
if %ATTEMPT% GEQ 3 (
  >> daily\logs\runner.log echo %DATE% %TIME% gave up: no daily\%TODAY%\index.html after %ATTEMPT% attempts
  exit /b 1
)
rem ping as the delay: timeout.exe fails when the task has no console input.
ping -n %RETRY_WAIT_SECONDS% 127.0.0.1 >nul
goto attempt

rem One phase: name, model. Keeps its exit code for the caller.
:phase
>> daily\logs\runner.log echo %DATE% %TIME% phase %~1 on %~2
"%CLAUDE%" -p "/%~1" ^
  --model %~2 ^
  --setting-sources project ^
  --tools "Read,Write,Edit,Glob,Grep,Bash,WebFetch,WebSearch,Agent,Skill,ToolSearch" ^
  --permission-mode acceptEdits ^
  --allowedTools "Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Agent,Skill,ToolSearch,mcp__claude_ai_Indeed__search_jobs,mcp__claude_ai_Indeed__get_job_details,Bash(bun --version),Bash(bun run .agents/skills/*),Bash(python tools/*),Bash(python daily/daily_state.py *),Bash(lualatex *),Bash(cd daily/*),Bash(cd cv*),Bash(rm -f *),Bash(rm -rf daily/*),Bash(mkdir -p *),Bash(mkdir *),Bash(mv *),Bash(cmd //c start *)" ^
  >> "daily\logs\%TODAY%.log" 2>&1
exit /b %ERRORLEVEL%

:delivered
start "" "http://localhost:8765/%TODAY%/"
exit /b 0
