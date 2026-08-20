@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set COMPOSE=docker compose -f deploy/docker-compose.yml
set TMPD=%TEMP%\wsu_install

if not exist "%TMPD%" mkdir "%TMPD%"

echo.
echo ============================================================
echo   2조 SOL로몬 - 우송대 학사 AI 챗봇 설치
echo ============================================================
echo.
echo   전체 40~60분 걸립니다. 이 창을 닫지 마세요.
echo   중간에 실패해도 다시 실행하면 끝난 단계는 건너뜁니다.
echo.

REM ============================================================
REM  1. 사전 점검
REM ============================================================
echo [1/6] 사전 점검
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo   [X] Docker 를 찾을 수 없습니다.
  echo.
  echo       Docker Desktop 을 먼저 설치하세요.
  echo       https://www.docker.com/products/docker-desktop
  echo       설치 후 한 번 실행해 초기 설정을 마치고 다시 시도하세요.
  goto :fail
)

docker info >nul 2>&1
if errorlevel 1 (
  echo   [X] Docker 는 설치돼 있으나 실행 중이 아닙니다.
  echo       Docker Desktop 을 실행한 뒤 다시 시도하세요.
  goto :fail
)
echo   [O] Docker 실행 중

where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo   [X] NVIDIA 드라이버를 찾을 수 없습니다.
  echo.
  echo       https://www.nvidia.com/download/index.aspx
  echo       설치 후 재부팅하고 다시 시도하세요.
  goto :fail
)

nvidia-smi --query-gpu=name,compute_cap,memory.total --format=csv,noheader > "%TMPD%\gpu.txt" 2>nul
set /p GPULINE=<"%TMPD%\gpu.txt"
for /f "tokens=1,2,3 delims=," %%A in ("!GPULINE!") do (
  set GPUNAME=%%A
  set CAP=%%B
  set VRAM=%%C
)
set CAP=!CAP: =!
echo   [O] GPU: !GPUNAME! ^(compute !CAP!,!VRAM!^)

if not "!CAP!"=="8.6" (
  set CAPNUM=!CAP:.=!
  echo.
  echo   [!] 이 프로젝트는 compute capability 8.6 기준으로 빌드됩니다.
  echo       이 PC 는 !CAP! 입니다.
  echo.
  echo       BackEnd\Dockerfile 의 CMAKE_CUDA_ARCHITECTURES 값을
  echo       86 에서 !CAPNUM! 으로 바꾼 뒤 실행하는 것을 권장합니다.
  echo       ^(8.6 보다 낮으면 답변 생성이 동작하지 않습니다^)
  echo.
  choice /c YN /m "       그대로 진행할까요"
  if errorlevel 2 goto :abort
)

docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu22.04 nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo   [X] 컨테이너에서 GPU 를 인식하지 못합니다.
  echo       Docker Desktop 설정에서 WSL2 백엔드가 켜져 있는지 확인하세요.
  goto :fail
)
echo   [O] 컨테이너 GPU 인식

if not exist "deploy\data\seed.sql" (
  echo   [X] deploy\data 가 없습니다. 배포 압축을 통째로 풀었는지 확인하세요.
  goto :fail
)
echo   [O] 학사 데이터 확인
echo.

REM ============================================================
REM  2. 환경변수
REM ============================================================
echo [2/6] 환경변수 준비
echo.
if exist "BackEnd\.env" (
  echo   BackEnd\.env 가 이미 있습니다 - 건너뜁니다.
) else (
  copy /y "deploy\.env.example" "BackEnd\.env" >nul
  powershell -NoProfile -Command "-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 48 | %%{[char]$_})" > "%TMPD%\key.txt"
  set /p SECRET=<"%TMPD%\key.txt"
  powershell -NoProfile -Command ^
    "$p='BackEnd\.env'; $enc=New-Object System.Text.UTF8Encoding $false; $c=[System.IO.File]::ReadAllLines($p,[System.Text.Encoding]::UTF8) -replace '^SECRET_KEY=.*','SECRET_KEY=!SECRET!'; [System.IO.File]::WriteAllLines($p,$c,$enc)"
  del "%TMPD%\key.txt" >nul 2>&1
  echo   BackEnd\.env 생성 완료 ^(SECRET_KEY 자동 생성^)
)
echo.

REM ============================================================
REM  3. 이미지 빌드
REM ============================================================
echo [3/6] Docker 이미지 빌드
echo       llama-cpp 를 CUDA 소스에서 빌드합니다. 20~40분 걸립니다.
echo.
%COMPOSE% build
if errorlevel 1 (
  echo   [X] 빌드 실패
  goto :fail
)
echo   [O] 빌드 완료
echo.

REM ============================================================
REM  4. 모델 다운로드
REM ============================================================
echo [4/6] 모델 다운로드 ^(약 7 GB^)
echo.
%COMPOSE% run --rm --no-deps backend python3 -m scripts.download_models
if errorlevel 1 (
  echo   [X] 모델 다운로드 실패 - 네트워크 확인 후 다시 실행하세요.
  echo       받은 부분은 유지되며 이어받습니다.
  goto :fail
)
echo.

REM ============================================================
REM  5. 기동
REM ============================================================
echo [5/6] 서비스 기동
echo.
%COMPOSE% up -d
if errorlevel 1 (
  echo   [X] 기동 실패
  goto :fail
)
echo   임베딩 모델 최초 다운로드로 3~5분 더 걸립니다. 대기 중...

set /a WAIT=0
:waitloop
timeout /t 10 /nobreak >nul
set /a WAIT+=10
curl -s -o nul -w "%%{http_code}" http://localhost:8000/health > "%TMPD%\health.txt" 2>nul
set /p CODE=<"%TMPD%\health.txt"
if "!CODE!"=="200" goto :ready
if !WAIT! geq 900 (
  echo.
  echo   [X] 15분이 지나도 서버가 응답하지 않습니다.
  echo       로그를 확인하세요:
  echo       %COMPOSE% logs backend
  goto :fail
)
echo       대기 !WAIT!초...
goto :waitloop

:ready
echo   [O] 서버 준비 완료
echo.

REM ============================================================
REM  6. 학사 데이터 반입
REM ============================================================
echo [6/6] 학사 데이터 반입
echo.
%COMPOSE% exec -T backend python3 -m scripts.import_deploy_data
if errorlevel 1 (
  echo   [X] 데이터 반입 실패
  goto :fail
)

rd /s /q "%TMPD%" >nul 2>&1

echo.
echo ============================================================
echo   설치 완료
echo ============================================================
echo.
echo   학생 화면    http://localhost:5173
echo   API 문서     http://localhost:8000/docs
echo.
echo   1. 위 주소에서 회원가입하세요.
echo   2. 관리자 권한이 필요하면 아래를 실행하세요.
echo      ^(20250001 자리에 가입한 학번을 넣으세요^)
echo.
echo      %COMPOSE% exec postgres psql -U postgres -d school_chatbot -c "UPDATE student SET role='admin' WHERE student_no='20250001';"
echo.
echo   다음부터 켤 때는 이 파일 대신 아래 한 줄이면 됩니다.
echo      %COMPOSE% up -d
echo.
pause
exit /b 0

:abort
echo.
echo   설치를 중단했습니다.
pause
exit /b 1

:fail
echo.
echo ------------------------------------------------------------
echo   설치를 완료하지 못했습니다. 위 메시지를 확인하세요.
echo   문제를 해결한 뒤 이 파일을 다시 실행하면 됩니다.
echo   ^(이미 끝난 단계는 자동으로 건너뜁니다^)
echo ------------------------------------------------------------
echo.
pause
exit /b 1
