@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=all"

if /i "%MODE%"=="check"   goto :check
if /i "%MODE%"=="linux"   goto :linux
if /i "%MODE%"=="android" goto :android
if /i "%MODE%"=="all"     goto :all
echo usage: build.bat [all^|linux^|android^|check] & exit /b 1

:check
echo [build] python + unit tests + lint
where python >nul 2>nul || (echo [error] python missing — install Python 3.11+ & exit /b 1)
cd desktop
python -m pip install -q pytest ruff python-dateutil || exit /b 1
python -m pytest tests/ -q || exit /b 1
ruff check . || exit /b 1
cd ..
echo [build] prerequisites for the full build:
where java >nul 2>nul && (java -version 2>&1 | findstr /r "version") || echo [warn]  java missing — Android build needs JDK 17
if "%ANDROID_HOME%"=="" (echo [warn]  ANDROID_HOME not set — Android build needs the SDK) else echo [build] ANDROID_HOME=%ANDROID_HOME%
where wsl >nul 2>nul && echo [build] wsl found — Linux executable will be built via WSL || echo [warn]  wsl missing — Linux executable can only be built on Linux/WSL
goto :eof

:linux
where wsl >nul 2>nul || (echo [error] the Linux executable is built on Linux — use WSL (wsl not found) & exit /b 1)
wsl bash ./build.sh linux || exit /b 1
goto :eof

:android
where java >nul 2>nul || (echo [error] JDK 17 missing & exit /b 1)
if "%ANDROID_HOME%"=="" (echo [error] ANDROID_HOME not set & exit /b 1)
cd android
if exist gradlew.bat (set "GRADLE=gradlew.bat") else (where gradle >nul 2>nul && (set "GRADLE=gradle") || (echo [error] no gradle/gradlew — run 'gradle wrapper' once & exit /b 1))
echo [build] %GRADLE% :app:assembleRelease
%GRADLE% :app:assembleRelease || exit /b 1
cd ..
if not exist dist\android mkdir dist\android
copy /y android\app\build\outputs\apk\release\app-release.apk dist\android\erinnerungen-1.0.0.apk >nul
echo [build] android OK -^> dist\android\erinnerungen-1.0.0.apk
goto :eof

:all
call :check || exit /b 1
call :linux || exit /b 1
call :android || exit /b 1
goto :eof
